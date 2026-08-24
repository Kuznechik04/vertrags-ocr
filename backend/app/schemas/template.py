from pydantic import BaseModel, ConfigDict


class TemplateFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    field_key: str
    field_label: str
    sort_order: int
    patterns: list[str] | None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    fields: list[TemplateFieldOut]


class TemplateCreate(BaseModel):
    key: str
    name: str


class TemplateFieldCreate(BaseModel):
    field_key: str
    field_label: str
    patterns: list[str] | None = None


class TemplateFieldUpdate(BaseModel):
    field_label: str
    patterns: list[str] | None = None
