from pydantic import BaseModel


class CustomerContext(BaseModel):
  """티앤미미 중식당 봇이 응대하는 고객 정보 (개인화 응대용)."""
  customer_id: int
  name: str
  membership: str = "일반"  # 일반 / VIP


class RestaurantInputGuardrailOutput(BaseModel):
  """입력 가드레일 판정 결과 (off-topic 또는 부적절한 언어면 거부)."""
  is_off_topic: bool
  is_inappropriate: bool
  reason: str


class RestaurantOutputGuardrailOutput(BaseModel):
  """출력 가드레일 판정 결과 (비전문적/무례하거나 내부 정보 노출이면 차단)."""
  is_unprofessional: bool
  reveals_internal_info: bool
  reason: str
