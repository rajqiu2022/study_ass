#!/bin/bash
# ============================================
# 学习助手 - testcase.work 部署脚本
# 适用于 Ubuntu 20.04 / 22.04 / 24.04
# 端口：8088
# ============================================

set -e

APP_DIR="/opt/study-assistant"
APP_USER="www-data"
PYTHON_VERSION="python3"
SERVICE_NAME="study-assistant"

echo "========================================"
echo "  学习助手 - 一键部署 (端口 8088)"
echo "========================================"

# ----- 1. 系统更新 & 安装依赖 -----
echo ""
echo "[1/7] 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx git > /dev/null 2>&1
echo "  ✅ 系统依赖安装完成"

# ----- 2. 创建应用目录 -----
echo ""
echo "[2/7] 部署应用文件..."
mkdir -p $APP_DIR
mkdir -p /var/log/gunicorn

# 如果是首次部署，复制文件；如果是更新，同步文件
if [ -d ".git" ]; then
    echo "  检测到 Git 仓库，使用 Git 同步..."
    cd $APP_DIR
    git pull origin main 2>/dev/null || true
else
    echo "  复制应用文件到 $APP_DIR ..."
    # 复制所有文件（排除不需要的）
    rsync -av --exclude='__pycache__' \
              --exclude='*.pyc' \
              --exclude='venv' \
              --exclude='.git' \
              --exclude='.codebuddy' \
              --exclude='instance' \
              ./ $APP_DIR/
fi
echo "  ✅ 应用文件部署完成"

# ----- 3. Python 虚拟环境 -----
echo ""
echo "[3/7] 配置 Python 虚拟环境..."
cd $APP_DIR

if [ ! -d "venv" ]; then
    $PYTHON_VERSION -m venv venv
    echo "  创建新的虚拟环境"
fi

source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "  ✅ Python 依赖安装完成"

# ----- 4. 环境变量配置 -----
echo ""
echo "[4/7] 配置环境变量..."
if [ ! -f "$APP_DIR/.env" ]; then
    # 生成随机 SECRET_KEY
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > $APP_DIR/.env << EOF
SECRET_KEY=$SECRET
FLASK_ENV=production
EOF
    echo "  ✅ .env 已生成（SECRET_KEY 已自动生成）"
else
    echo "  ✅ .env 已存在，跳过"
fi

# ----- 5. 初始化数据库 -----
echo ""
echo "[5/7] 初始化数据库..."
cd $APP_DIR
source venv/bin/activate
python3 -c "
from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()
    print('  ✅ 数据库初始化完成')
"

# ----- 6. 配置 Systemd 服务 -----
echo ""
echo "[6/7] 配置系统服务..."
cp $APP_DIR/deploy/knowledge-app.service /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}
echo "  ✅ 系统服务配置完成（已设为开机自启）"

# ----- 7. 配置 Nginx -----
echo ""
echo "[7/7] 配置 Nginx..."
cp $APP_DIR/deploy/nginx.conf /etc/nginx/sites-available/${SERVICE_NAME}
ln -sf /etc/nginx/sites-available/${SERVICE_NAME} /etc/nginx/sites-enabled/${SERVICE_NAME}

# 注意：不删除默认站点，因为服务器上还有其他服务
# rm -f /etc/nginx/sites-enabled/default

# 测试并重启 Nginx
nginx -t
systemctl restart nginx
echo "  ✅ Nginx 配置完成"

# ----- 8. 设置文件权限 -----
echo ""
echo "设置文件权限..."
chown -R $APP_USER:$APP_USER $APP_DIR
chown -R $APP_USER:$APP_USER /var/log/gunicorn
chmod -R 755 $APP_DIR
echo "  ✅ 权限设置完成"

# ----- 完成 -----
echo ""
echo "========================================"
echo "  🎉 部署完成！"
echo "========================================"
echo ""
echo "  访问地址: https://testcase.work:8088"
echo "  管理账号: admin"
echo "  管理密码: 123321"
echo ""
echo "  常用命令:"
echo "    查看状态:  systemctl status ${SERVICE_NAME}"
echo "    重启应用:  systemctl restart ${SERVICE_NAME}"
echo "    查看日志:  journalctl -u ${SERVICE_NAME} -f"
echo "    Nginx日志: tail -f /var/log/nginx/access.log"
echo ""
echo "  ⚠️  请尽快登录后台修改管理员密码！"
echo "========================================"
