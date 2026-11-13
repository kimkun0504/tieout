from types import SimpleNamespace

from tieout.llm import AnthropicHeaderMapper, describe_samples, mapper_from_env, parse_suggestions
from tieout.mapping import map_columns


class FakeMessages:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


def test_sample_values_never_leave_the_machine():
    fake = FakeMessages('{"mappings": [{"header": "Occupant Nm", "field": "tenant", "confidence": 0.9}]}')
    mapper = AnthropicHeaderMapper(client=fake)
    out = map_columns(
        {0: "Unit", 1: "Occupant Nm", 2: "Rent"},
        {1: ["Garcia, Maria", "Nguyen, David"], 2: ["1,425.00"]},
        mapper,
    )
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "Garcia" not in prompt and "Nguyen" not in prompt
    assert '"Occupant Nm": long text' in prompt
    assert fake.calls[0]["model"] == "claude-haiku-5-5" and fake.calls[0]["temperature"] == 0
    m = {x.header: x for x in out}["Occupant Nm"]
    assert (m.field, m.method, m.confidence) == ("tenant", "mapper", 0.8)


def test_fails_closed_on_api_errors_and_bad_answers():
    assert AnthropicHeaderMapper(client=FakeMessages(error=TimeoutError())).suggest({"X": []}, ["tenant"]) == {}
    assert AnthropicHeaderMapper(client=FakeMessages("I think X is the tenant")).suggest({"X": []}, ["tenant"]) == {}


def test_parse_suggestions_is_strict():
    text = """Here you go: {"mappings": [
        {"header": "A", "field": "tenant", "confidence": 0.95},
        {"header": "B", "field": "tenant", "confidence": 0.9},
        {"header": "C", "field": "made_up", "confidence": 0.9},
        {"header": "Nope", "field": "sqft", "confidence": 0.9},
        {"header": "D", "field": "sqft", "confidence": 0.3},
        {"header": "E", "field": "deposit", "confidence": "high"}
    ]}"""
    assert parse_suggestions(text, {"A", "B", "C", "D", "E"}, {"tenant", "sqft", "deposit"}) == {"A": ("tenant", 0.95)}


def test_describe_samples_by_shape():
    assert describe_samples(["$1,200.00", "950"]) == "money-like"
    assert describe_samples(["01/15/2026"]) == "date-like"
    assert describe_samples(["A101"]) == "short code"
    assert describe_samples([]) == "empty"


def test_mapper_is_off_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("TIEOUT_LLM", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert mapper_from_env() is None
    monkeypatch.setenv("TIEOUT_LLM", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert mapper_from_env() is None
