from pydantic import BaseModel


class CustomerContext(BaseModel):
  """티앤미미 중식당 봇이 응대하는 고객 정보 (개인화 응대용)."""
  customer_id: int
  name: str
  membership: str = "일반"  # 일반 / VIP


class RestaurantTopicGuardrailOutput(BaseModel):
  """Triage 입력 가드레일 판정 결과."""
  is_off_topic: bool
  reason: str
