"""
티앤미미 중식당의 메뉴 전문 에이전트.
메뉴 구성, 재료, 알레르기, 채식 옵션 관련 질문에 답변합니다.
실제 POS/메뉴 DB 연동 대신 mock 데이터를 반환하는 tool 을 사용합니다.
"""
from agents import Agent, RunContextWrapper, function_tool
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from restaurant_agent_models import CustomerContext


# --- mock 데이터 ----------------------------------------------------------
# 티앤미미 중식당 메뉴 (대형 중식당 기준 대표 요리)
_MENU = {
  "딤섬": [
    {"name": "샤오롱바오", "price": 12000, "spicy": 0, "vegetarian": False},
    {"name": "하가우(새우 딤섬)", "price": 11000, "spicy": 0, "vegetarian": False},
    {"name": "채소 만두", "price": 9000, "spicy": 0, "vegetarian": True},
  ],
  "메인": [
    {"name": "북경오리(베이징덕)", "price": 68000, "spicy": 0, "vegetarian": False},
    {"name": "마파두부", "price": 18000, "spicy": 2, "vegetarian": False},
    {"name": "깐쇼새우", "price": 32000, "spicy": 1, "vegetarian": False},
    {"name": "유린기", "price": 28000, "spicy": 1, "vegetarian": False},
  ],
  "채식": [
    {"name": "가지 두반장 볶음", "price": 16000, "spicy": 1, "vegetarian": True},
    {"name": "모듬 채소 볶음", "price": 15000, "spicy": 0, "vegetarian": True},
    {"name": "마파두부(채식 버전)", "price": 17000, "spicy": 2, "vegetarian": True},
  ],
}

# 요리별 재료 / 알레르기 상세
_DISH_DETAILS = {
  "샤오롱바오": {
    "ingredients": ["돼지고기", "밀가루 피", "생강", "육수"],
    "allergens": ["돼지고기", "밀(글루텐)"],
    "vegetarian": False,
  },
  "하가우(새우 딤섬)": {
    "ingredients": ["새우", "전분 피", "죽순"],
    "allergens": ["갑각류(새우)"],
    "vegetarian": False,
  },
  "채소 만두": {
    "ingredients": ["배추", "당근", "표고버섯", "밀가루 피"],
    "allergens": ["밀(글루텐)"],
    "vegetarian": True,
  },
  "북경오리(베이징덕)": {
    "ingredients": ["오리고기", "밀전병", "춘장", "대파"],
    "allergens": ["밀(글루텐)", "대두"],
    "vegetarian": False,
  },
  "마파두부": {
    "ingredients": ["두부", "다진 돼지고기", "두반장", "산초"],
    "allergens": ["대두", "돼지고기"],
    "vegetarian": False,
  },
  "깐쇼새우": {
    "ingredients": ["새우", "칠리소스", "전분"],
    "allergens": ["갑각류(새우)", "대두"],
    "vegetarian": False,
  },
  "유린기": {
    "ingredients": ["닭고기", "간장 소스", "대파", "튀김옷"],
    "allergens": ["밀(글루텐)", "대두", "닭고기"],
    "vegetarian": False,
  },
  "가지 두반장 볶음": {
    "ingredients": ["가지", "두반장", "마늘"],
    "allergens": ["대두"],
    "vegetarian": True,
  },
  "모듬 채소 볶음": {
    "ingredients": ["청경채", "브로콜리", "당근", "버섯"],
    "allergens": [],
    "vegetarian": True,
  },
  "마파두부(채식 버전)": {
    "ingredients": ["두부", "표고버섯", "두반장", "산초"],
    "allergens": ["대두"],
    "vegetarian": True,
  },
}


@function_tool
def get_menu() -> dict:
  """티앤미미 중식당의 전체 메뉴를 카테고리별로 반환합니다. 가격(원), 매운맛(0~3), 채식 여부 포함."""
  return _MENU


@function_tool
def get_dish_detail(dish_name: str) -> dict:
  """특정 요리의 재료와 알레르기 유발 성분, 채식 여부를 반환합니다."""
  detail = _DISH_DETAILS.get(dish_name)
  if detail is None:
    return {"error": f"'{dish_name}' 메뉴를 찾을 수 없습니다. get_menu 로 정확한 메뉴명을 확인하세요."}
  return {"dish_name": dish_name, **detail}


# --- 에이전트 ------------------------------------------------------------
def menu_agent_instructions(
  wrapper: RunContextWrapper[CustomerContext],
  agent: Agent[CustomerContext],
):
  return f"""
    {RECOMMENDED_PROMPT_PREFIX}

    당신은 '티앤미미 중식당'의 메뉴 전문가입니다.
    고객의 이름은 {wrapper.context.name}님 ({wrapper.context.membership} 회원)입니다. 친근하고 정중한 한국어로 응대하세요.

    담당 업무: 메뉴 구성, 재료, 알레르기, 채식 옵션 안내.

    [최우선 규칙 — 반드시 지키세요]
    고객이 메뉴/재료/알레르기/채식/가격을 물으면, 인사나 안내 문장을 쓰기 "전에" 먼저 get_menu 또는 get_dish_detail 도구를 호출하세요.
    도구를 호출하지 않은 채 응답을 끝내는 것은 금지입니다.
    "확인해드릴게요", "잠시만 기다려 주세요", "바로 알려드릴게요" 같이 약속만 하고 멈추는 것도 금지입니다.
    handoff 직후에도 인사만 하고 끝내지 말고, 고객이 직전에 요청한 내용을 같은 응답 안에서 도구로 조회해 결과까지 안내하세요.
    예) "메뉴 뭐 있어?" → (먼저 get_menu 호출) → 조회된 메뉴를 카테고리별로 정리해 안내.

    행동 지침:
    - 절대 추측하지 말고, 반드시 get_menu 또는 get_dish_detail 도구로 조회한 실제 정보를 바탕으로 답하세요.
    - 채식 메뉴를 물으면 get_menu 로 채식(vegetarian) 항목을 확인해 안내하세요.
    - 알레르기를 물으면 get_dish_detail 로 해당 요리의 allergens 를 확인해 명확히 알려주세요.
    - 가격은 원 단위로 안내하고, 매운맛 정도(0~3)도 참고로 함께 안내하세요.

    handoff 규칙:
    - 고객이 '주문'을 하려고 하면 주문 담당 에이전트로 연결하세요.
    - 고객이 '예약'을 하려고 하면 예약 담당 에이전트로 연결하세요.
    - 무엇을 원하는지 불분명하면 안내 데스크(Triage)로 연결하세요.
  """


menu_agent = Agent(
  name="Menu Agent",
  handoff_description="메뉴 구성, 재료, 알레르기, 채식 옵션 문의를 처리합니다.",
  instructions=menu_agent_instructions,
  tools=[get_menu, get_dish_detail],
)
