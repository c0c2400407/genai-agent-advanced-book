"""LangGraphの実行順序と分岐。各ステップの仕事はsteps.pyへ渡す。"""

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from src.configs import Settings
from src.llm import LLM
from src.models import AgentResult, AgentState, Plan, SearchState, Subtask
from src.prompts import HelpDeskAgentPrompts
from src.security import validate_question
from src.steps import AgentSteps


class HelpDeskAgent:
    def __init__(self, settings: Settings, tools=None, prompts=None):
        self.settings = settings
        self.llm = LLM(settings)
        self.steps = AgentSteps(settings, self.llm, tools or [], prompts or HelpDeskAgentPrompts())

    def create_graph(self):
        """計画を作り、サブタスクを順番に処理し、最終回答にまとめる。"""
        workflow = StateGraph(AgentState)
        workflow.add_node("create_plan", self.steps.create_plan)
        workflow.add_node("execute_subtasks", self._execute_subtask)
        workflow.add_node("create_answer", self.steps.create_answer)
        workflow.add_edge(START, "create_plan")
        workflow.add_edge("create_plan", "execute_subtasks")
        workflow.add_conditional_edges(
            "execute_subtasks",
            self._next_subtask,
            {"execute_subtasks": "execute_subtasks", "create_answer": "create_answer"},
        )
        workflow.add_edge("create_answer", END)
        return workflow.compile()

    def _create_subgraph(self):
        """検索→回答→評価。NGなら検索へ戻り、試行上限でも終了する。"""
        workflow = StateGraph(SearchState)
        workflow.add_node("select_tools", self.steps.select_tools)
        workflow.add_node("execute_tools", self.steps.execute_tools)
        workflow.add_node("create_subtask_answer", self.steps.create_subtask_answer)
        workflow.add_node("reflect_subtask", self.steps.reflect_subtask)
        workflow.add_edge(START, "select_tools")
        workflow.add_edge("select_tools", "execute_tools")
        workflow.add_edge("execute_tools", "create_subtask_answer")
        workflow.add_edge("create_subtask_answer", "reflect_subtask")
        workflow.add_conditional_edges(
            "reflect_subtask",
            self._after_evaluation,
            {"retry": "select_tools", "finish": END},
        )
        return workflow.compile()

    def _next_subtask(self, state: AgentState):
        if state["current_step"] < len(state["plan"]):
            return "execute_subtasks"
        return "create_answer"

    def _after_evaluation(self, state: SearchState):
        if state["is_completed"] or state["challenge_count"] >= self.settings.max_challenges:
            return "finish"
        return "retry"

    def _execute_subtask(self, state: AgentState):
        result = self._create_subgraph().invoke(
            {
                "question": state["question"],
                "plan": state["plan"],
                "subtask": state["plan"][state["current_step"]],
                "is_completed": False,
                "challenge_count": 0,
            }
        )
        subtask = Subtask(
            task_name=result["subtask"],
            tool_results=result["tool_results"],
            reflection_results=result["reflection_results"],
            is_completed=result["is_completed"],
            subtask_answer=result["subtask_answer"],
            challenge_count=result["challenge_count"],
        )
        return {"subtask_results": [subtask], "current_step": state["current_step"] + 1}

    def run_agent(self, question: str) -> AgentResult:
        validate_question(question)
        # 外部トレースを抑止し、1つの言語モデルを順番に使う。
        with tracing_context(enabled=False):
            result = self.create_graph().invoke(
                {"question": question, "current_step": 0},
                config={"max_concurrency": 1},
            )
        return AgentResult(
            question=question,
            plan=Plan(subtasks=result["plan"]),
            subtasks=result["subtask_results"],
            answer=result["last_answer"],
        )
