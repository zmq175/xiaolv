# 实施

首个CLI→HTTP纵向红绿测试，然后逐行为追加错误配置、初始化覆盖和迁移检查。Uvicorn使用官方Server/Config接口；密码初始化复用pwdlib；管理员需要的秘密保存在仓库外或gitignore覆盖的runtime目录。

参考Uvicorn官方：https://www.uvicorn.org/settings/

无新迁移，检查当前Alembic head。真实本地子进程测试使用隔离PG及随机端口；不连接QQ、模型服务或部署云主机。
