"""Tool output models."""

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["in_force", "repealed", "unknown"]


class ActInfo(BaseModel):
    id: int = Field(description="Id for get_act, get_article and find_in_act.")
    title: str
    type: str | None = Field(description="The kind of act, such as a law or a Cabinet decision.")
    number: str | None = Field(description="The act's own number, such as 785 or 674s.")
    status: Status = Field(
        description="in_force, repealed, or unknown when the site says otherwise."
    )
    status_text: str | None = Field(description="The status as the site words it.")
    accepted: str | None = Field(description="Date the act was adopted, YYYY-MM-DD.")
    effective: str | None = Field(
        description="Date it took effect, YYYY-MM-DD, when the site says."
    )
    register_code: str | None = Field(description="Code in the State Register of Legal Acts.")
    url: str = Field(description="The act's page on e-qanun.az.")


class ActSearch(BaseModel):
    count: int = Field(description="Acts matching the search, not only those returned.")
    offset: int
    limit: int
    next_offset: int | None = Field(
        description="Pass as offset for the next acts; null at the end."
    )
    results: list[ActInfo]
    notes: list[str]
    fetched_at: str = Field(description="When this server read the site, UTC.")
    source: str
    attribution: str


class Publication(BaseModel):
    source: str = Field(description="Where the act was published, such as Azərbaycan Qəzeti.")
    details: list[str] = Field(description="Date, issue and item, each as 'name: value'.")


class AmendmentNote(BaseModel):
    marker: int = Field(description="The number in square brackets in the text, such as [12].")
    text: str = Field(description="What the note says, usually which law changed the passage.")


class ActReference(BaseModel):
    label: str = Field(description="The words in the text that link to the act, such as KMQ23.")
    act_id: int = Field(description="Id for get_act, get_article and find_in_act.")
    title: str | None = Field(description="What the site says the link leads to, when it says.")
    url: str = Field(description="The linked act's page on e-qanun.az.")


class ActDetails(BaseModel):
    status: Literal["ok", "too_large"] = Field(description="ok, or why no text is returned.")
    reason: str | None = Field(description="Set when status is not ok.")
    act: ActInfo
    register_date: str | None = Field(
        description="Date of entry in the State Register, YYYY-MM-DD."
    )
    class_codes: list[str] = Field(description="Codes of the legal classifier.")
    publications: list[Publication]
    edition_dates: list[str] = Field(
        description="Editions the site keeps of the act, by the date each took effect, newest "
        "first. Only the current edition is read."
    )
    structure: Literal["articles", "paragraphs"] | None = Field(
        description="articles when the act is divided into articles; null when it was not read."
    )
    articles: int | None = Field(description="Number of articles; null when there are none.")
    first_article: str | None
    last_article: str | None
    total_chars: int | None = Field(description="Length of the act's whole text.")
    offset: int
    next_offset: int | None = Field(
        description="Pass as offset for the next text; null at the end."
    )
    text: str | None = Field(
        description="The text from offset, with [n] markers of amendment notes."
    )
    amendment_notes: list[AmendmentNote] = Field(
        description="The notes whose markers are in this piece of text."
    )
    references: list[ActReference] = Field(
        description="Links to other acts in this piece of text: the acts it cites, and court "
        "decisions the site marks as KM or KMQ."
    )
    notes: list[str]
    fetched_at: str = Field(description="When this server read the site, UTC.")
    source: str
    attribution: str


class ArticleText(BaseModel):
    act: ActInfo
    article: str
    heading: str = Field(description="The article's heading line, such as 'Maddə 7. Title'.")
    text: str = Field(description="The article from offset, with [n] markers of amendment notes.")
    total_chars: int = Field(description="Length of the article's whole text.")
    offset: int
    next_offset: int | None = Field(description="Pass as offset for the rest; null at the end.")
    amendment_notes: list[AmendmentNote] = Field(
        description="The notes whose markers are in the heading or in this piece of text."
    )
    references: list[ActReference] = Field(
        description="Links to other acts anywhere in the article: the acts it cites, and court "
        "decisions the site marks as KM or KMQ."
    )
    previous_article: str | None
    next_article: str | None
    notes: list[str]
    fetched_at: str = Field(description="When this server read the site, UTC.")
    source: str
    attribution: str


class TextMatch(BaseModel):
    article: str | None = Field(description="Article number; null in an act without articles.")
    heading: str
    matches: int = Field(description="Occurrences of the words in the article or paragraph.")
    snippet: str
    position: int = Field(
        description="Where it starts in the act's text: the offset to give get_act to read from it."
    )


class TextSearch(BaseModel):
    act: ActInfo
    query: str
    unit: Literal["article", "paragraph"] = Field(
        description="What each result is: an article, or a paragraph in an act without articles."
    )
    count: int = Field(description="Articles or paragraphs matching, not only those returned.")
    offset: int
    limit: int
    next_offset: int | None = Field(
        description="Pass as offset for the next results; null at the end."
    )
    results: list[TextMatch]
    notes: list[str]
    fetched_at: str = Field(description="When this server read the site, UTC.")
    source: str
    attribution: str
