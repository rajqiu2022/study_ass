from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('请输入用户名和密码', 'error')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=True)
            next_page = request.args.get('next')
            if user.is_admin:
                return redirect(next_page or url_for('admin.admin_dashboard'))
            return redirect(next_page or url_for('main.dashboard'))
        else:
            flash('用户名或密码错误', 'error')
    
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        errors = []
        if not username:
            errors.append('请输入用户名')
        if len(username) < 2 or len(username) > 20:
            errors.append('用户名长度需要在2-20个字符之间')
        if not password:
            errors.append('请输入密码')
        if len(password) < 6:
            errors.append('密码长度至少6个字符')
        if password != confirm_password:
            errors.append('两次输入的密码不一致')
        if User.query.filter_by(username=username).first():
            errors.append('用户名已存在')
        if username.lower() == 'admin':
            errors.append('不能使用此用户名')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html')
        
        user = User(username=username, role='user')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        errors = []
        if not current_user.check_password(old_password):
            errors.append('原密码错误')
        if len(new_password) < 6:
            errors.append('新密码长度至少6个字符')
        if new_password != confirm_password:
            errors.append('两次输入的密码不一致')
        
        if errors:
            for error in errors:
                flash(error, 'error')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('密码修改成功', 'success')
            return redirect(url_for('main.dashboard'))
    
    return render_template('auth/change_password.html')
