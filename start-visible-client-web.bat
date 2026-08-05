@echo off
rem 与 start-visible-client.bat 相同，但额外开启"网页版同款替换"真实链路。
rem 用法：双击本文件启动本地客户端；登录后进入"同款替换/图文同款"页，
rem 点"打开网页版替换"即可打开 http://127.0.0.1:9081/replacement（自动带当前账号 token）。
rem   MATRIX_REPLACEMENT_WEB_ENABLED=1  开启 /replacement 网页与 /api/replacement/* 接口
rem   VIDEO_REPLACEMENT_SERVICE_MODE=shared  视频替换走共享服务/真实管线（默认 legacy 走旧 Qt 路径）
set "MATRIX_REPLACEMENT_WEB_ENABLED=1"
set "VIDEO_REPLACEMENT_SERVICE_MODE=shared"
call "%~dp0start-visible-client.bat"
