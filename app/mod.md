
UI에 데이터 추가 시 흐름

app/models.py 의 Skill dataclass에 추가 필드를 정의합니다.
app/normalizer.py에서
return Skill(...)필드 정의 후, app/ui/main_window.py의 _load_data()에서 번역 추가.
