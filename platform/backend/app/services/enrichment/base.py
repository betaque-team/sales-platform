from dataclasses import dataclass, field


@dataclass
class EnrichmentResult:
    success: bool = False
    provider: str = ""
    company_data: dict = field(default_factory=dict)  # domain, industry, description, founded_year, etc.
    contacts: list[dict] = field(default_factory=list)  # [{first_name, last_name, title, email, phone, linkedin_url, ...}]
    offices: list[dict] = field(default_factory=list)  # [{label, city, country, is_headquarters, ...}]
    error: str = ""
