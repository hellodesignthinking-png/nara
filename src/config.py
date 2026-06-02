"""
설정 관리 모듈
.env 파일에서 환경변수를 로드하고 전역 설정 객체를 제공합니다.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv


# 프로젝트 루트 디렉터리
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
DB_PATH = DATA_DIR / "nara.db"


@dataclass
class Config:
    """전역 설정 객체"""

    # 공공데이터포털 API
    data_go_kr_api_key: str = ""

    # 네이버 검색 API
    naver_client_id: str = ""
    naver_client_secret: str = ""

    # OpenAI API
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Google Gemini API
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # LLM 엔진 선택 (openai / gemini)
    llm_engine: str = "gemini"

    # 이메일 설정
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_recipients: list[str] = field(default_factory=list)

    # 분석 설정
    keywords: list[str] = field(default_factory=list)
    min_relevance_score: int = 40
    past_years: int = 2

    # 경로
    project_root: Path = PROJECT_ROOT
    data_dir: Path = DATA_DIR
    attachments_dir: Path = ATTACHMENTS_DIR
    db_path: Path = DB_PATH

    @property
    def settings_path(self) -> Path:
        """settings.json 파일의 경로를 반환합니다."""
        return Path(self.db_path).parent / "settings.json"

    def __repr__(self) -> str:
        return (
            f"Config(llm_engine={self.llm_engine!r}, "
            f"openai_api_key={'****' if self.openai_api_key else 'None'}, "
            f"gemini_api_key={'****' if self.gemini_api_key else 'None'}, "
            f"data_go_kr_api_key={'****' if self.data_go_kr_api_key else 'None'}, "
            f"smtp_password={'****' if self.smtp_password else 'None'}, "
            f"db_path={self.db_path!r})"
        )

    def validate(self) -> list[str]:
        """필수 설정이 누락되었는지 검증합니다. 누락된 항목 목록을 반환합니다."""
        warnings = []
        if not self.data_go_kr_api_key:
            warnings.append("DATA_GO_KR_API_KEY가 설정되지 않았습니다. 나라장터 API를 사용할 수 없습니다.")
        if not self.naver_client_id or not self.naver_client_secret:
            warnings.append("네이버 API 키가 설정되지 않았습니다. 뉴스 수집이 비활성화됩니다.")
        if self.llm_engine == "gemini":
            if not self.gemini_api_key:
                warnings.append("GEMINI_API_KEY가 설정되지 않았습니다. AI 분석이 비활성화됩니다.")
        else:
            if not self.openai_api_key:
                warnings.append("OPENAI_API_KEY가 설정되지 않았습니다. AI 분석이 비활성화됩니다.")
        return warnings


def _safe_int(value: str, default: int) -> int:
    """환경변수 문자열을 안전하게 int로 변환합니다."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# 싱글턴 인스턴스
_config_instance: Config | None = None


def load_config(force_reload: bool = False) -> Config:
    """
    환경변수에서 설정을 로드합니다.

    싱글턴 패턴을 사용하여 최초 호출 시에만 실제 로드를 수행하고,
    이후 호출에서는 캐시된 인스턴스를 반환합니다.

    Args:
        force_reload: True이면 캐시를 무시하고 설정을 다시 로드합니다.
    """
    global _config_instance

    if _config_instance is not None and not force_reload:
        return _config_instance

    # .env 파일 로드
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 디렉터리 생성
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

    # 이메일 수신자 파싱
    recipients_str = os.getenv("EMAIL_RECIPIENTS", "")
    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]

    # 키워드 파싱
    keywords_str = os.getenv("KEYWORDS", "AI,인공지능,데이터,마케팅,컨설팅,SW개발,플랫폼")
    keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

    _config_instance = Config(
        data_go_kr_api_key=os.getenv("DATA_GO_KR_API_KEY", ""),
        naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        llm_engine=os.getenv("LLM_ENGINE", "gemini"),
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=_safe_int(os.getenv("SMTP_PORT", "587"), 587),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        email_recipients=recipients,
        keywords=keywords,
        min_relevance_score=_safe_int(os.getenv("MIN_RELEVANCE_SCORE", "40"), 40),
        past_years=_safe_int(os.getenv("PAST_YEARS", "2"), 2),
    )

    return _config_instance
