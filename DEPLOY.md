# 腾讯云部署指南

## 前提条件

- 腾讯云轻量应用服务器（推荐 Ubuntu 22.04）
- 已开放 **80 端口**（在腾讯云控制台 → 防火墙规则中添加）

## 部署步骤

### 第一步：上传代码到服务器

在你的**本地电脑**上执行（把 `你的服务器IP` 替换为实际 IP）：

```bash
# 打包项目（排除不需要的文件）
cd 项目目录
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='venv' --exclude='.git' --exclude='.codebuddy' --exclude='instance' -czf knowledge-app.tar.gz .

# 上传到服务器
scp knowledge-app.tar.gz root@你的服务器IP:/tmp/
```

### 第二步：在服务器上执行部署

SSH 登录服务器后执行：

```bash
# 解压到目标目录
mkdir -p /opt/knowledge-app
cd /opt/knowledge-app
tar -xzf /tmp/knowledge-app.tar.gz

# 赋予脚本执行权限并运行
chmod +x deploy.sh
sudo bash deploy.sh
```

脚本会自动完成：
- ✅ 安装 Python3、Nginx 等系统依赖
- ✅ 创建虚拟环境并安装 Python 包
- ✅ 自动生成安全的 SECRET_KEY
- ✅ 初始化数据库
- ✅ 配置 Gunicorn + Nginx
- ✅ 设置开机自启

### 第三步：访问应用

部署完成后，浏览器访问：

```
http://你的服务器IP
```

- 管理员账号：`admin`
- 管理员密码：`123321`

> ⚠️ 请首次登录后立即修改管理员密码！

## 常用运维命令

```bash
# 查看应用状态
systemctl status knowledge-app

# 重启应用
systemctl restart knowledge-app

# 停止应用
systemctl stop knowledge-app

# 查看应用日志（实时）
journalctl -u knowledge-app -f

# 查看 Nginx 访问日志
tail -f /var/log/nginx/access.log

# 查看 Gunicorn 错误日志
tail -f /var/log/gunicorn/error.log
```

## 更新应用

当代码有更新时：

```bash
# 本地重新打包上传
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='venv' --exclude='.git' --exclude='.codebuddy' --exclude='instance' -czf knowledge-app.tar.gz .
scp knowledge-app.tar.gz root@你的服务器IP:/tmp/

# 服务器上执行
cd /opt/knowledge-app
tar -xzf /tmp/knowledge-app.tar.gz --exclude='.env' --exclude='instance'
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart knowledge-app
```

> 注意：更新时会保留 `.env` 和 `instance/`（数据库），不会丢数据。

## 绑定域名（可选）

1. 将域名解析到服务器 IP
2. 修改 Nginx 配置：

```bash
sudo vi /etc/nginx/sites-available/knowledge-app
# 将 server_name _; 改为 server_name 你的域名;
sudo nginx -t && sudo systemctl restart nginx
```

## 开启 HTTPS（可选）

```bash
# 安装 certbot
sudo apt install -y certbot python3-certbot-nginx

# 申请证书（需先绑定域名）
sudo certbot --nginx -d 你的域名

# 自动续期
sudo certbot renew --dry-run
```

## 腾讯云防火墙配置

确保在腾讯云控制台开放以下端口：

| 端口 | 协议 | 用途 |
|------|------|------|
| 22   | TCP  | SSH 登录 |
| 80   | TCP  | HTTP 访问 |
| 443  | TCP  | HTTPS 访问（如需） |
