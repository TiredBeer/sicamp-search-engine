from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Complexity(BaseModel):
    time: str = Field(default="", max_length=200)
    memory: str = Field(default="", max_length=200)


class Statement(BaseModel):
    canonical_name: str = ""
    format: Literal["standard", "interactive", "second_run", "output_only"] = "standard"
    abstract: str = ""
    objects: list[dict] = Field(default_factory=list)
    task: str = ""
    guarantees: list[str] = Field(default_factory=list)
    inferred_properties: list[str] = Field(default_factory=list)
    image_required: bool = False


class SolutionData(BaseModel):
    source: Literal["code", "llm"] = "llm"
    trusted: bool = False
    key_idea: str = Field(default="", max_length=2000)
    sketch: str = ""
    facts: list[dict] = Field(default_factory=list)
    reduction: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=100)
    free_tags: list[str] = Field(default_factory=list, max_length=100)
    difficulty: int | None = Field(default=None, ge=1, le=10)
    difficulty_reason: str = ""
    complexity: Complexity = Field(default_factory=Complexity)
    prerequisite: list[str] = Field(default_factory=list)

    @field_validator("tags", "free_tags")
    @classmethod
    def validate_tags(cls, values):
        if any(not v.strip() or len(v.strip()) > 120 for v in values):
            raise ValueError("Название тега должно содержать от 1 до 120 символов")
        return [v.strip() for v in values]


class SolutionInput(SolutionData):
    code: str | None = Field(default=None, max_length=500000)
    origin: str = Field(default="", max_length=1000)


class ManualSolution(SolutionInput):
    difficulty: int = Field(ge=1, le=10)
    complexity: Complexity

    @field_validator("complexity")
    @classmethod
    def require_complexity(cls, value):
        if not value.time.strip() or not value.memory.strip():
            raise ValueError("Укажите асимптотику времени и памяти")
        return value


class Analysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statement: Statement
    solutions: list[SolutionData] = Field(default_factory=list, max_length=100)


class TagAnalysis(BaseModel):
    solutions: list[SolutionData] = Field(default_factory=list, max_length=100)


class ProblemInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    statement: str = Field(min_length=1, max_length=500000)
    abstract: str | None = Field(default=None, max_length=500000)
    origin: str = Field(default="", max_length=1000)
    solutions: list[SolutionInput] = Field(default_factory=list, max_length=100)

    @field_validator("title", "statement")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Поле не может быть пустым")
        return value.strip()


class InternalProblemInput(ProblemInput):
    title: str = Field(default="Новая задача", min_length=1, max_length=300)


class ProblemEdit(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    statement: str = Field(min_length=1, max_length=500000)
    abstract: str = Field(default="", max_length=500000)
    origin: str = Field(default="", max_length=1000)

    _not_blank = field_validator("title", "statement")(ProblemInput.not_blank.__func__)


class TagInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["closed", "free"]

    @field_validator("name")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Название тега не может быть пустым")
        return value.strip()
