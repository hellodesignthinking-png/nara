"""
앱 전역 상태 관리 모듈.

순환 임포트를 방지하기 위해 app.py와 routes 간의 공유 상태를
이 모듈에서 관리합니다.
"""

# 스케줄러 인스턴스 (lifespan에서 초기화)
scheduler = None

# 스케줄 분석 작업 함수 참조 (lifespan에서 설정)
scheduled_analysis_job = None
