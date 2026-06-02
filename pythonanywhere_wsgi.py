"""
PythonAnywhere WSGI Configuration File

이 파일은 PythonAnywhere의 Web 탭에서 WSGI configuration file로 설정합니다.
FastAPI(ASGI)를 PythonAnywhere의 WSGI 서버에서 실행하기 위한 래퍼입니다.
"""

import sys
import os

# 프로젝트 루트를 Python 경로에 추가
project_home = '/home/YOUR_USERNAME/nara'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# 환경변수 설정
os.environ['SCHEDULER_ENABLED'] = 'false'  # PythonAnywhere에서는 스케줄러 비활성화

# FastAPI 앱 임포트
from src.api.app import app

# ASGI를 WSGI로 래핑 (a]sync FastAPI → sync WSGI)
# PythonAnywhere는 기본적으로 WSGI만 지원하므로 asgiref 사용
try:
    from asgiref.wsgi import WsgiToAsgi
    # 이 방향이 아니라 반대로 해야 함
    raise ImportError
except ImportError:
    pass

# 방법 2: uvicorn.middleware.asgi 사용하지 않고
# PythonAnywhere의 Always-on Task로 uvicorn 직접 실행 (추천)
# 아래는 Flask 호환 래퍼로 기본 페이지만 서빙

from flask import Flask, send_from_directory, send_file
flask_app = Flask(__name__, static_folder=os.path.join(project_home, 'static'))

@flask_app.route('/')
def index():
    return send_file(os.path.join(project_home, 'static', 'index.html'))

@flask_app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(os.path.join(project_home, 'static'), filename)

# WSGI application 엔트리포인트
application = flask_app
