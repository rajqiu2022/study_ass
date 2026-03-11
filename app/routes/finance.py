"""Finance tracking - report and manual entry routes."""
import json
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import FinanceRecord

finance_bp = Blueprint('finance', __name__, url_prefix='/finance')


@finance_bp.route('/')
@login_required
def finance_page():
    """Render the finance report page."""
    # Default: current month
    today = date.today()
    start_date = request.args.get('start', today.replace(day=1).strftime('%Y-%m-%d'))
    end_date = request.args.get('end', today.strftime('%Y-%m-%d'))

    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        start_dt = today.replace(day=1)
        end_dt = today

    # Query records in range
    records = FinanceRecord.query.filter(
        FinanceRecord.user_id == current_user.id,
        FinanceRecord.record_date >= start_dt,
        FinanceRecord.record_date <= end_dt
    ).order_by(FinanceRecord.record_date.desc(), FinanceRecord.created_at.desc()).all()

    # Compute stats
    total_expense = sum(r.amount for r in records if r.record_type == 'expense')
    total_income = sum(r.amount for r in records if r.record_type == 'income')
    balance = total_income - total_expense

    # Category breakdown
    expense_by_cat = {}
    income_by_cat = {}
    for r in records:
        bucket = expense_by_cat if r.record_type == 'expense' else income_by_cat
        bucket[r.category] = bucket.get(r.category, 0) + r.amount

    # Sort by amount desc
    expense_by_cat = dict(sorted(expense_by_cat.items(), key=lambda x: -x[1]))
    income_by_cat = dict(sorted(income_by_cat.items(), key=lambda x: -x[1]))

    # Daily trend (for chart)
    daily_expense = {}
    daily_income = {}
    d = start_dt
    while d <= end_dt:
        ds = d.strftime('%Y-%m-%d')
        daily_expense[ds] = 0
        daily_income[ds] = 0
        d += timedelta(days=1)
    for r in records:
        ds = r.record_date.strftime('%Y-%m-%d')
        if r.record_type == 'expense':
            daily_expense[ds] = daily_expense.get(ds, 0) + r.amount
        else:
            daily_income[ds] = daily_income.get(ds, 0) + r.amount

    return render_template('finance/report.html',
                           records=records,
                           start_date=start_dt.strftime('%Y-%m-%d'),
                           end_date=end_dt.strftime('%Y-%m-%d'),
                           total_expense=total_expense,
                           total_income=total_income,
                           balance=balance,
                           expense_by_cat=expense_by_cat,
                           income_by_cat=income_by_cat,
                           daily_expense=json.dumps(daily_expense),
                           daily_income=json.dumps(daily_income),
                           expense_categories=FinanceRecord.EXPENSE_CATEGORIES,
                           income_categories=FinanceRecord.INCOME_CATEGORIES)


@finance_bp.route('/add', methods=['POST'])
@login_required
def add_record():
    """Manually add a finance record."""
    data = request.get_json()
    record_type = data.get('record_type', 'expense')
    amount = data.get('amount')
    category = data.get('category', '')
    description = data.get('description', '')
    record_date_str = data.get('record_date', '')

    if not amount or float(amount) <= 0:
        return jsonify({'error': '金额必须大于0'}), 400
    if not category:
        return jsonify({'error': '请选择分类'}), 400

    try:
        record_date = datetime.strptime(record_date_str, '%Y-%m-%d').date() if record_date_str else date.today()
    except ValueError:
        record_date = date.today()

    record = FinanceRecord(
        user_id=current_user.id,
        record_type=record_type,
        amount=float(amount),
        category=category,
        description=description,
        record_date=record_date,
        source='manual'
    )
    db.session.add(record)
    db.session.commit()

    return jsonify({'ok': True, 'record': record.to_dict()})


@finance_bp.route('/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_record(record_id):
    """Delete a finance record."""
    record = FinanceRecord.query.filter_by(id=record_id, user_id=current_user.id).first()
    if not record:
        return jsonify({'error': '记录不存在'}), 404
    db.session.delete(record)
    db.session.commit()
    return jsonify({'ok': True})


@finance_bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    """API: get summary stats for a date range."""
    today = date.today()
    start_date = request.args.get('start', today.replace(day=1).strftime('%Y-%m-%d'))
    end_date = request.args.get('end', today.strftime('%Y-%m-%d'))

    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': '日期格式错误'}), 400

    records = FinanceRecord.query.filter(
        FinanceRecord.user_id == current_user.id,
        FinanceRecord.record_date >= start_dt,
        FinanceRecord.record_date <= end_dt
    ).all()

    total_expense = sum(r.amount for r in records if r.record_type == 'expense')
    total_income = sum(r.amount for r in records if r.record_type == 'income')

    expense_by_cat = {}
    income_by_cat = {}
    for r in records:
        bucket = expense_by_cat if r.record_type == 'expense' else income_by_cat
        bucket[r.category] = bucket.get(r.category, 0) + r.amount

    return jsonify({
        'total_expense': total_expense,
        'total_income': total_income,
        'balance': total_income - total_expense,
        'expense_by_cat': expense_by_cat,
        'income_by_cat': income_by_cat,
        'record_count': len(records)
    })
