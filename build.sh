#!/bin/bash
# Render.com 빌드 스크립트
# data 디렉토리 생성 (DB 저장용)
mkdir -p data
pip install --upgrade pip
pip install -r requirements.txt
