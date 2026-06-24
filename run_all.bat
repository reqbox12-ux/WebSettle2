@echo off
chcp 65001 >nul
cd /d %~dp0
title 라온스포츠 통합 (ERP 8503 + CRM 8502)
echo ============================================
echo  라온스포츠 통합 서버 (로컬 검증용)
echo  ERP : http://localhost:8503
echo  CRM : http://localhost:8502
echo  DB  : data\settlement.db (ERP/CRM 공유)
echo ============================================

REM CRM 포털 (FastAPI 8502) — 새 창
start "CRM 8502" cmd /k py -m uvicorn branch_server:app --host 0.0.0.0 --port 8502 --reload

REM ERP (FastAPI 8503) — 현재 창
py -m uvicorn main:app --host 0.0.0.0 --port 8503 --reload
