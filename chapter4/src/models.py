import operator
from typing import TYPE_CHECKING, Literal, Annotated, TypedDict

from pydantic import BaseModel, Field, ConfigDict

if TYPE_CHECKING:
    from qdrant_client.models import ScoredPoint


class SafeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SearchOutput(SafeModel):
    file_name: str = Field(max_length=256, description="The file name")
    content: str = Field(max_length=4096, description="The content of the file")

    @classmethod
    def from_hit(cls, hit: dict) -> "SearchOutput":
        return cls(file_name=hit["_source"]["file_name"], content=hit["_source"]["content"])

    @classmethod
    def from_point(cls, point: "ScoredPoint") -> "SearchOutput":
        if point.payload is None:
            raise ValueError("Payload is None")
        return cls(file_name=point.payload["file_name"], content=point.payload["content"])


class Plan(SafeModel):
    subtasks: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        ..., min_length=1, max_length=2, description="問題を解決するためのサブタスクリスト"
    )


class ToolSelection(SafeModel):
    tool_name: Literal["search_xyz_manual", "search_xyz_qa"]
    query: str = Field(min_length=1, max_length=256)


class ToolResult(SafeModel):
    tool_name: str = Field(..., description="ツールの名前")
    args: str = Field(..., description="ツールの引数")
    results: list[SearchOutput] = Field(..., description="ツールの結果")


class ReflectionResult(SafeModel):
    advice: str = Field(
        ...,
        max_length=1000,
        description="評価がNGの場合は、別のツールを試す、別の文言でツールを試すなど、なぜNGなのかとどうしたら改善できるかを考えアドバイスを作成してください。\
アドバイスの内容は過去のアドバイスと計画内の他のサブタスクと重複しないようにしてください。\
アドバイスの内容をもとにツール選択・実行からやり直します。",
    )
    is_completed: bool = Field(
        ...,
        strict=True,
        description="ツールの実行結果と回答から、サブタスクに対して正しく回答できているかの評価結果",
    )


class Subtask(BaseModel):
    task_name: str = Field(..., description="サブタスクの名前")
    tool_results: list[list[ToolResult]] = Field(..., description="サブタスクの結果")
    reflection_results: list[ReflectionResult] = Field(..., description="サブタスクの評価結果")
    is_completed: bool = Field(..., description="サブタスクが完了しているかどうか")
    subtask_answer: str = Field(..., description="サブタスクの回答")
    challenge_count: int = Field(..., description="サブタスクの挑戦回数")


class AgentResult(BaseModel):
    question: str = Field(..., description="ユーザーの元の質問")
    plan: Plan = Field(..., description="エージェントの計画")
    subtasks: list[Subtask] = Field(..., description="サブタスクのリスト")
    answer: str = Field(..., description="最終的な回答")


class AgentState(TypedDict):
    """全体の進捗。サブタスクの結果は実行順に追加する。"""

    question: str
    plan: list[str]
    current_step: int
    subtask_results: Annotated[list[Subtask], operator.add]
    last_answer: str


class SearchState(TypedDict):
    """1サブタスクの検索と評価。各試行の履歴を追加して残す。"""

    question: str
    plan: list[str]
    subtask: str
    is_completed: bool
    challenge_count: int
    tool_calls: list[dict]
    tool_results: Annotated[list[list[ToolResult]], operator.add]
    reflection_results: Annotated[list[ReflectionResult], operator.add]
    subtask_answer: str
