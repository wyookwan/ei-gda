import os
import re
import secrets
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from config import Config, assert_safe_runtime
from extensions import db
from models import User, Template, Standard, StandardItem, DocumentCheck, DocumentFile, CommitteeAssignment, CommitteeReview, AuditLog
from utils import json_dumps, json_loads, extract_headings_from_text, save_uploaded_file, login_required
from services.domain_service import get_pack, list_packs, evidence_review
from services.pdf_service import extract_text_from_pdf, extract_pages_from_pdf, combine_documents_for_analysis
from services.kg_service import build_knowledge_graph, retrieve_relevant_items
from services.local_model_service import score_with_local_model, local_model_enabled
from services.gemini_service import score_with_gemini, gemini_enabled
from services.scoring_service import run_hybrid_compliance, build_evidence_map
from services.standards_catalog import load_catalog, standard_metadata, item_metadata
from services.report_service import generate_system_report, generate_committee_report
from governance_routes import bp as governance_bp
from pilot_routes import bp as pilot_bp
from services import access_policy as ap
from services import model_gate
from services.file_safety import inspect_pdf
from services.thaid_service import (init_thaid, is_configured as thaid_is_configured, authorize_redirect as thaid_authorize_redirect, exchange_code_and_get_profile, normalize_profile, remember_token, revoke_token)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    init_thaid(app)
    app.register_blueprint(governance_bp)
    app.register_blueprint(pilot_bp)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['REPORT_FOLDER'], exist_ok=True)

    @app.before_request
    def enforce_csrf():
        """Every state-changing request needs the session token, except in the unit-test client."""
        if request.method in ('GET', 'HEAD', 'OPTIONS') or (app.testing and not app.config.get('CSRF_ENFORCE_IN_TESTS')):
            return None
        expected = session.get('_csrf_token')
        supplied = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token') or ''
        if not expected or not secrets.compare_digest(str(supplied), str(expected)):
            app.logger.warning('CSRF token rejected for %s', request.path)
            return 'Session expired or invalid form token. Please go back, reload the page and try again.', 400
        return None

    @app.after_request
    def add_security_layers(response):
        """Add the CSRF token to every POST form on the way out, so old templates stay protected."""
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        if response.mimetype == 'text/html' and not response.direct_passthrough:
            html = response.get_data(as_text=True)
            token = session.get('_csrf_token')
            if token is None:
                token = secrets.token_urlsafe(32)
                session['_csrf_token'] = token
            html = html.replace('__CSRF_TOKEN__', token)
            field = f'<input type="hidden" name="_csrf_token" value="{token}">'
            html = re.sub(r'(<form\b[^>]*\bmethod=["\']?post["\']?[^>]*>)', lambda m: m.group(1) + field, html, flags=re.I)
            response.set_data(html)
        return response

    def write_log(action, target_type=None, target_id=None, detail=None):
        db.session.add(AuditLog(
            user_id=session.get('user_id'), actor_email=session.get('email'), action=action,
            target_type=target_type, target_id=str(target_id) if target_id else None,
            detail=(detail or '')[:15000]
        ))
        db.session.commit()

    @app.context_processor
    def inject_globals():
        return {'session': session, 'gemini_enabled': gemini_enabled(), 'local_model_enabled': local_model_enabled(), 'thaid_enabled': thaid_is_configured(), 'platform_name': 'Ei-GDA', 'domain_packs': list_packs()}

    def redirect_by_role():
        return redirect(url_for('gov.overview'))

    def remember_org_context(user):
        """Pick the first active membership as the working organization; the user can switch later."""
        rows = ap.memberships(user.id)
        session['org_id'] = rows[0].organization_id if rows else None

    def denied(target_type, target_id, action):
        ap.deny(target_type, target_id, action)
        flash('Access denied.', 'danger')
        return redirect(url_for('committee_dashboard' if session.get('role') == 'committee' else 'gov.overview'))

    def build_recommendations(test_suite_name, missing_sections):
        if not missing_sections:
            return 'ควรเพิ่มหลักฐาน owner, review cycle และ traceable evidence เพื่อสนับสนุนการประเมิน assurance'
        lines = [f'คำแนะนำสำหรับ Test Suite {test_suite_name}']
        for sec in missing_sections[:20]:
            lines.append(f"- เพิ่มหัวข้อ '{sec}' พร้อมวัตถุประสงค์ ขอบเขต ผู้รับผิดชอบ หลักฐาน และรอบการทบทวน")
        lines += ['', 'ข้อเสนอเพิ่มเติม:', '- ระบุ owner/champion ของแต่ละหัวข้อ', '- เพิ่มหลักฐานอ้างอิง เช่น SOP, policy, risk register, DPIA, testing report', '- กำหนด review cycle และ escalation path']
        return '\n'.join(lines)

    @app.route('/')
    def home():
        if session.get('user_id'):
            return redirect_by_role()
        return redirect(url_for('login'))

    @app.route('/healthz')
    def healthz():
        """Container health endpoint; does not expose configuration or secrets."""
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify({'status': 'ok'}), 200
        except Exception:
            db.session.rollback()
            return jsonify({'status': 'unhealthy'}), 503

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip().lower()
            organization = request.form.get('organization', '').strip()
            password = request.form.get('password', '').strip()
            if not all([full_name, email, password]):
                flash('Please fill in all required fields.', 'danger')
                return redirect(url_for('register'))
            if len(password) < 10:
                flash('Password must be at least 10 characters.', 'danger')
                return redirect(url_for('register'))
            if User.query.filter_by(email=email).first():
                flash('Email already exists.', 'warning')
                return redirect(url_for('register'))
            db.session.add(User(full_name=full_name, email=email, organization=organization,
                                password_hash=generate_password_hash(password), password_plain=None,
                                role='user', is_active=True, auth_provider='local'))
            db.session.commit()
            flash('Registration completed.', 'success')
            return redirect(url_for('login'))
        return render_template('auth/register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username_or_email = request.form.get('username_or_email', '').strip()
            password = request.form.get('password', '').strip()
            alias = (app.config.get('ADMIN_LOGIN_ALIAS') or '').lower()
            if alias and username_or_email.lower() == alias:
                user = User.query.filter_by(role='admin').first()
            else:
                user = User.query.filter(db.func.lower(User.email) == username_or_email.lower()).first()
            if user and user.is_active and user.password_hash and check_password_hash(user.password_hash, password):
                user.last_login_at = __import__('datetime').datetime.utcnow()
                db.session.commit()
                session['user_id'] = user.id
                session['email'] = user.email
                session['full_name'] = user.full_name
                session['role'] = user.role
                remember_org_context(user)
                write_log('login', 'user', user.id, f'{user.email} logged in')
                return redirect_by_role()
            flash('Invalid credentials.', 'danger')
        return render_template('auth/login.html')


    @app.route('/auth/thaid/login')
    def thaid_login():
        if session.get('user_id'):
            return redirect_by_role()
        if not thaid_is_configured():
            flash('ThaiD login is not configured. Please contact the system administrator.', 'warning')
            return redirect(url_for('login'))
        redirect_uri = app.config.get('THAID_REDIRECT_URI') or url_for('thaid_callback', _external=True)
        try:
            return thaid_authorize_redirect(redirect_uri)
        except Exception as exc:
            app.logger.exception('Unable to start ThaiD authentication')
            try:
                write_log('thaid_login_error', 'authentication', None, str(exc))
            except Exception:
                pass
            flash('Unable to connect to ThaiD. Please try again or use local sign-in.', 'danger')
            return redirect(url_for('login'))

    @app.route('/auth/thaid/callback')
    def thaid_callback():
        if request.args.get('error'):
            detail = request.args.get('error_description') or request.args.get('error')
            flash(f'ThaiD authentication was not completed: {detail}', 'warning')
            return redirect(url_for('login'))
        try:
            token, raw_profile = exchange_code_and_get_profile()
            profile = normalize_profile(raw_profile)
            user = User.query.filter_by(external_subject=profile['subject']).first()
            if not user:
                user = User.query.filter_by(email=profile['email']).first()
            if not user:
                # Federated users have no local password. A random unusable hash
                # prevents password login while satisfying the legacy schema.
                user = User(
                    full_name=profile['full_name'],
                    email=profile['email'],
                    organization=app.config.get('THAID_ORGANIZATION_DEFAULT') or None,
                    password_hash=generate_password_hash(os.urandom(48).hex()),
                    password_plain=None,
                    role='user',
                    is_active=True,
                    auth_provider='thaid',
                    external_subject=profile['subject'],
                    thaid_reference_hash=profile['reference_hash'],
                )
                db.session.add(user)
            else:
                user.full_name = profile['full_name'] or user.full_name
                user.auth_provider = 'thaid'
                user.external_subject = profile['subject']
                user.thaid_reference_hash = profile['reference_hash']
            if not user.is_active:
                db.session.rollback()
                flash('Your account is disabled. Please contact the administrator.', 'danger')
                return redirect(url_for('login'))
            user.last_login_at = __import__('datetime').datetime.utcnow()
            db.session.commit()
            session.clear()
            session['user_id'] = user.id
            session['email'] = user.email
            session['full_name'] = user.full_name
            session['role'] = user.role
            session['auth_provider'] = 'thaid'
            remember_org_context(user)
            remember_token(token)
            write_log('thaid_login', 'user', user.id, f'{user.email} logged in through ThaiD')
            return redirect_by_role()
        except Exception as exc:
            db.session.rollback()
            app.logger.exception('ThaiD callback failed')
            try:
                write_log('thaid_callback_error', 'authentication', None, str(exc))
            except Exception:
                pass
            flash('ThaiD authentication failed. Please verify the endpoint and redirect URI configuration.', 'danger')
            return redirect(url_for('login'))

    @app.route('/logout')
    def logout():
        try:
            if session.get('auth_provider') == 'thaid' and session.get('thaid_access_token'):
                revoke_token(session.get('thaid_access_token'))
            write_log('logout', 'user', session.get('user_id'), f"{session.get('email')} logged out")
        except Exception:
            app.logger.exception('Logout or ThaiD token revocation failed')
        session.clear()
        flash('Logged out.', 'success')
        return redirect(url_for('login'))

    # User routes
    @app.route('/check/<int:check_id>/domain-review', methods=['GET', 'POST'])
    @login_required()
    def domain_review(check_id):
        check = DocumentCheck.query.get_or_404(check_id)
        perms = ap.check_permissions(check)
        if ap.VIEW not in perms:
            ap.deny('document_check', check.id, ap.VIEW)
            return 'Access denied', 403
        pack = get_pack(check.domain_slug or 'general') or get_pack('general')
        stored = json_loads(check.domain_review_json, default={}) or {}
        if 'domain_review_csrf' not in session:
            session['domain_review_csrf'] = secrets.token_urlsafe(32)
        if request.method == 'POST':
            if not secrets.compare_digest(request.form.get('csrf_token',''), session['domain_review_csrf']):
                return 'Invalid form token', 400
            if not (ap.EDIT in perms or (session.get('role') == 'admin' and ap.REVIEW in perms)):
                return 'Review updates restricted to owner and admin', 403
            statuses = {c['id']: request.form.get('status_' + c['id'], 'not_assessed') for c in pack['controls']}
            reasons = {c['id']:request.form.get('reason_' + c['id'], '').strip()[:500] for c in pack['controls']}
            if any(statuses[c['id']] == 'not_applicable' and len(reasons[c['id']]) < 8 for c in pack['controls']):
                flash('กรุณาระบุเหตุผลอย่างน้อย 8 ตัวอักษรสำหรับ Not Applicable', 'danger')
                return redirect(url_for('domain_review', check_id=check.id))
            try:
                result = evidence_review(pack, statuses)
            except ValueError:
                return 'Invalid review', 400
            check.domain_review_json = json_dumps({'pack_version': pack['pack_version'], 'statuses':statuses, 'reasons':reasons, 'result':result,
                'reviewed_by':session['user_id'], 'reviewed_at':__import__('datetime').datetime.utcnow().isoformat()})
            db.session.commit()
            write_log('domain_evidence_review', 'document_check', check.id, f"domain={pack['slug']}; coverage={result['coverage_percent']}")
            flash('บันทึกการตรวจสอบหลักฐานแล้ว (ยังไม่ใช่ผลรับรองการปฏิบัติตามกฎหมาย)', 'success')
            return redirect(url_for('domain_review', check_id=check.id))
        return render_template('user/domain_review.html', check=check, pack=pack, stored=stored, csrf_token=session['domain_review_csrf'],
                               editable=ap.EDIT in perms or (session.get('role') == 'admin' and ap.REVIEW in perms))

    @app.route('/dashboard')
    @login_required(role='user')
    def dashboard():
        checks = [c for c in DocumentCheck.query.filter_by(user_id=session['user_id']).order_by(DocumentCheck.created_at.desc()).all()
                  if ap.VIEW in ap.check_permissions(c)]
        test_suites = Template.query.filter_by(is_enabled=True).order_by(Template.display_order, Template.name, Template.id).all()
        standards = Standard.query.filter_by(is_enabled=True).order_by(Standard.source_type.asc(), Standard.code.asc()).all()
        template_framework_map = {
            str(t.id): json_loads(t.applicable_framework_codes_json, default=[])
            for t in test_suites
        }
        template_info_map = {
            str(t.id): {
                'name': t.name,
                'description': t.description or '',
                'threshold': t.pass_threshold,
                'framework_codes': template_framework_map.get(str(t.id), [])
            }
            for t in test_suites
        }
        selected_domain = request.args.get('domain', 'general')
        if not get_pack(selected_domain):
            selected_domain = 'general'
        return render_template(
            'user/dashboard.html', selected_domain=selected_domain, checks=checks, test_suites=test_suites, standards=standards,
            test_suite_framework_map=template_framework_map, test_suite_info_map=template_info_map,
            catalog_metadata=standard_metadata()
        )

    def expected_evidence_for_item(item):
        """Return concise, human-readable evidence suggestions for Explorer only.

        This is presentation metadata, not a compliance conclusion. The actual assessment
        continues to use the selected reference items and document evidence.
        """
        researched = item_metadata().get(item.item_code)
        if researched:
            return researched['evidence_expected']
        text_blob = f"{item.category or ''} {item.title or ''}".lower()
        rules = [
            (('policy', 'นโยบาย', 'governance', 'กำกับดูแล'), 'Policy / governance charter / approved procedure'),
            (('role', 'responsib', 'owner', 'committee', 'บทบาท', 'ผู้รับผิดชอบ'), 'RACI / TOR / organization chart / appointment record'),
            (('risk', 'impact', 'ความเสี่ยง', 'ผลกระทบ'), 'Risk register / impact assessment / risk treatment plan'),
            (('privacy', 'personal data', 'pdpa', 'ข้อมูลส่วนบุคคล'), 'Privacy notice / RoPA / DPIA / consent or lawful-basis record'),
            (('security', 'cyber', 'access control', 'incident', 'ความมั่นคง'), 'Security architecture / access-control record / incident log / test report'),
            (('data quality', 'dataset', 'data ', 'ข้อมูล', 'lineage', 'provenance'), 'Dataset card / data dictionary / lineage / quality metrics / validation report'),
            (('bias', 'fairness', 'non-discrimination', 'อคติ', 'เป็นธรรม'), 'Bias/fairness evaluation / subgroup metrics / mitigation record'),
            (('transparen', 'explain', 'model card', 'โปร่งใส', 'อธิบาย'), 'Model card / transparency notice / explanation record / user disclosure'),
            (('test', 'validat', 'evaluat', 'robust', 'accuracy', 'performance', 'ทดสอบ'), 'Test plan / benchmark results / validation report / acceptance record'),
            (('monitor', 'review', 'audit', 'continuous', 'ติดตาม', 'ทบทวน'), 'Monitoring dashboard / audit report / review minutes / corrective action'),
            (('lifecycle', 'deploy', 'retire', 'decommission', 'change', 'วงจรชีวิต'), 'Lifecycle plan / release record / change log / retirement record'),
            (('purpose', 'scope', 'architecture', 'system', 'use case', 'ขอบเขต', 'สถาปัตยกรรม'), 'System specification / architecture diagram / use-case description / AI inventory'),
            (('training', 'competence', 'awareness', 'อบรม'), 'Training record / competency matrix / awareness material'),
            (('vendor', 'third-party', 'supplier', 'ผู้ให้บริการ'), 'Vendor assessment / contract / SLA / third-party due diligence'),
        ]
        for terms, evidence in rules:
            if any(term in text_blob for term in terms):
                return evidence
        return 'Approved document / operating record / traceable evidence relevant to this requirement'

    @app.route('/test-suites/explorer')
    @login_required()
    def test_suite_explorer():
        suites = Template.query.filter_by(is_enabled=True).order_by(Template.display_order, Template.name, Template.id).all()
        selected_id = request.args.get('suite', type=int)
        selected_suite = None
        if selected_id:
            selected_suite = next((suite for suite in suites if suite.id == selected_id), None)
        if not selected_suite and suites:
            selected_suite = suites[0]

        standards = []
        reference_groups = []
        domain_groups = []
        total_items = 0
        if selected_suite:
            allowed_codes = json_loads(selected_suite.applicable_framework_codes_json, default=[])
            standards = Standard.query.filter(Standard.code.in_(allowed_codes), Standard.is_enabled.is_(True)).order_by(
                Standard.source_type.asc(), Standard.code.asc()
            ).all() if allowed_codes else []
            standard_ids = [st.id for st in standards]
            items = StandardItem.query.filter(StandardItem.standard_id.in_(standard_ids), StandardItem.is_enabled.is_(True)).order_by(
                StandardItem.standard_id.asc(), StandardItem.order_index.asc(), StandardItem.id.asc()
            ).all() if standard_ids else []
            items_by_standard = {}
            for item in items:
                items_by_standard.setdefault(item.standard_id, []).append(item)
            total_items = len(items)

            type_labels = {
                'international_standard': 'International Standards',
                'international_standard_draft': 'International Standards — Draft readiness',
                'international_framework': 'International Frameworks',
                'international_principles': 'International Principles',
                'international_regulation': 'International Laws / Regulations',
                'thai_standard': 'Thai Standards / Data Governance',
                'thai_guideline': 'Thai Guidelines',
                'thai_law': 'Thai Laws & Regulations',
            }
            grouped_refs = {}
            for st in standards:
                ref = {
                    'standard': st,
                    'items': items_by_standard.get(st.id, []),
                    'type_label': type_labels.get(st.source_type, st.source_type.replace('_', ' ').title()),
                }
                grouped_refs.setdefault(st.source_type, []).append(ref)
            reference_groups = [
                {'key': key, 'label': type_labels.get(key, key.replace('_', ' ').title()), 'references': refs}
                for key, refs in grouped_refs.items()
            ]
            reference_groups.sort(key=lambda group: group['key'] != 'international_standard')

            # Domains are the Test Suite sections. Items are linked to a domain by normalized
            # token overlap; unmatched items remain visible under Cross-cutting requirements.
            sections = json_loads(selected_suite.sections_json, default=[])
            domain_map = {section: [] for section in sections}
            cross_cutting = []
            import re
            def tokens(value):
                return {t for t in re.findall(r'[a-zA-Z]{4,}|[ก-๙]{3,}', (value or '').lower())
                        if t not in {'with','from','that','this','และ','การ','ของ','สำหรับ'}}
            domain_tokens = {section: tokens(section) for section in sections}
            for item in items:
                item_tokens = tokens(f'{item.category or ""} {item.title or ""}')
                best_domain, best_score = None, 0
                for section, section_tokens in domain_tokens.items():
                    score = len(item_tokens & section_tokens)
                    if score > best_score:
                        best_domain, best_score = section, score
                payload = {
                    'item': item,
                    'standard': item.standard,
                    'evidence_expected': expected_evidence_for_item(item),
                    'provenance': item_metadata().get(item.item_code),
                }
                if best_domain:
                    domain_map[best_domain].append(payload)
                else:
                    cross_cutting.append(payload)
            domain_groups = [{'name': name, 'items': domain_map[name]} for name in sections]
            if cross_cutting:
                domain_groups.append({'name': 'Cross-cutting requirements', 'items': cross_cutting})

        return render_template(
            'user/test_suite_explorer.html', suites=suites, selected_suite=selected_suite,
            standards=standards, reference_groups=reference_groups, domain_groups=domain_groups,
            total_items=total_items, catalog_metadata=standard_metadata(),
            catalog_checked_on=load_catalog()['researched_on'],
            standards_watchlist=[row for row in load_catalog()['watchlist']
                                if selected_suite and row['suite'] == selected_suite.name]
        )

    @app.route('/test-suites/tree')
    @login_required()
    def test_suite_tree():
        if session.get('role') not in ('user', 'admin'):
            return 'Access denied', 403
        from services.suite_tree import build_suite_tree
        return render_template('user/test_suite_tree.html',
                               suite_tree=build_suite_tree(expected_evidence_for_item))

    @app.route('/upload', methods=['POST'])
    @login_required(role='user')
    def upload_document():
        files = [f for f in request.files.getlist('pdf_files') if f and f.filename]
        test_suite_id = request.form.get('test_suite_id', type=int)
        selected_standard_ids = request.form.getlist('standard_ids')
        data_classification = request.form.get('data_classification', '').strip().lower()
        domain_slug = request.form.get('domain_slug', 'general').strip()
        pack = get_pack(domain_slug)
        if not pack:
            flash('Invalid domain.', 'danger')
            return redirect(url_for('gov.domains'))
        domain_subdomain = request.form.get('domain_subdomain', '').strip()[:150]
        if domain_subdomain and domain_subdomain not in pack['subdomains']:
            flash('Invalid organization subtype.', 'danger')
            return redirect(url_for('gov.domain_detail', slug=domain_slug))
        assessment_use_case = request.form.get('assessment_use_case', '').strip()[:255]
        if data_classification not in ('open', 'confidential'):
            flash('Please select the document confidentiality level before uploading.', 'warning')
            return redirect(url_for('dashboard'))
        if request.form.get('classification_acknowledged') != data_classification:
            flash('กรุณาเลือกระดับเอกสารและกดรับทราบก่อนเริ่มประเมิน', 'warning')
            return redirect(url_for('dashboard'))
        if not files:
            flash('Please select at least one PDF file.', 'warning')
            return redirect(url_for('dashboard'))
        if any(not f.filename.lower().endswith('.pdf') for f in files):
            flash('All uploaded files must be PDF documents.', 'warning')
            return redirect(url_for('dashboard'))
        for f in files:
            problems = inspect_pdf(f.stream, app.config.get('MAX_PDF_PAGES', 400))
            if problems:
                flash(f'{f.filename}: ' + ' · '.join(problems), 'warning')
                return redirect(url_for('dashboard'))
        if not test_suite_id:
            flash('Please select a Test Suite.', 'warning')
            return redirect(url_for('dashboard'))
        if not selected_standard_ids:
            flash('Please select at least one standard, law, framework, or guideline.', 'warning')
            return redirect(url_for('dashboard'))

        test_suite = Template.query.get_or_404(test_suite_id)
        allowed_codes = set(json_loads(test_suite.applicable_framework_codes_json, default=[]))
        try:
            selected_ids_int = [int(x) for x in selected_standard_ids]
        except (TypeError, ValueError):
            flash('Invalid framework selection.', 'danger')
            return redirect(url_for('dashboard'))
        selected_frameworks = Standard.query.filter(Standard.id.in_(selected_ids_int), Standard.is_enabled == True).all()
        selected_codes = {x.code for x in selected_frameworks}
        if len(selected_frameworks) != len(set(selected_ids_int)):
            flash('One or more selected frameworks are invalid or disabled.', 'danger')
            return redirect(url_for('dashboard'))
        if allowed_codes and not selected_codes.issubset(allowed_codes):
            flash('One or more selected standards/laws are not applicable to the selected Test Suite.', 'danger')
            return redirect(url_for('dashboard'))

        # Create the assessment first, then attach multiple source PDFs.
        check = DocumentCheck(
            user_id=session['user_id'], template_id=test_suite.id,
            original_filename=files[0].filename if len(files) == 1 else f'{len(files)} source documents',
            stored_filename='', selected_standard_ids_json=json_dumps(selected_ids_int),
            data_classification=data_classification, processing_provider='pending',
            domain_slug=domain_slug, domain_subdomain=domain_subdomain, assessment_use_case=assessment_use_case,
            # Work started inside an organization context belongs to that organization.
            organization_id=ap.active_org_id() if ap.active_org_id() in ap.editor_org_ids() else None,
            # Completeness fields are retained only for DB backward compatibility and are no longer used.
            completeness_score=0.0, completeness_passed=True,
            thai_recommendations=''
        )
        db.session.add(check)
        db.session.flush()

        combined_parts = []
        total_pages = 0
        try:
            for f in files:
                stored_filename, full_path = save_uploaded_file(f, app.config['UPLOAD_FOLDER'])
                pages = extract_pages_from_pdf(full_path)
                extracted_text = '\n'.join(p.get('text', '') for p in pages)
                total_pages += len(pages)
                db.session.add(DocumentFile(
                    check_id=check.id,
                    original_filename=f.filename,
                    stored_filename=stored_filename,
                    page_count=len(pages),
                    extracted_text=extracted_text[:700000],
                    pages_json=json_dumps(pages)[:4000000],
                ))
                combined_parts.append(f"\n[SOURCE_FILE: {f.filename}]\n{extracted_text}")
                if not check.stored_filename:
                    check.stored_filename = stored_filename
            check.extracted_text = '\n'.join(combined_parts)[:1200000]
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        write_log('upload_documents', 'document_check', check.id, f'{len(files)} files; {total_pages} pages; domain={domain_slug}')
        flash(f'Uploaded {len(files)} PDF file(s). Starting evidence-driven compliance assessment.', 'success')
        return redirect(url_for('run_compliance', check_id=check.id, auto=1))

    @app.route('/check/<int:check_id>')
    @login_required()
    def view_check(check_id):
        check = DocumentCheck.query.get_or_404(check_id)
        if ap.VIEW not in ap.check_permissions(check):
            return denied('document_check', check.id, ap.VIEW)
        standard_summary = json_loads(check.standard_summary_json, default=[])
        compliance_results = json_loads(check.compliance_results_json, default=[])
        kg_summary = json_loads(check.kg_summary_json, default=[])
        gemini_summary = json_loads(check.gemini_summary_json, default={})
        local_model_summary = json_loads(check.local_model_summary_json, default={})
        category_summary = []
        maturity_distribution = {str(i): 0 for i in range(6)}
        for item in compliance_results:
            try:
                maturity_distribution[str(int(round(float(item.get('score', 0)))))] += 1
            except Exception:
                pass
        category_acc = {}
        for item in compliance_results:
            cat = item.get('category') or 'Other'
            try: sc = float(item.get('score', 0))
            except Exception: sc = 0
            category_acc.setdefault(cat, [0.0, 0]); category_acc[cat][0] += sc; category_acc[cat][1] += 1
        category_summary = [{'category': k, 'avg_score_0_to_5': round(v[0]/v[1],2), 'percent': round((v[0]/v[1])/5*100,2)} for k,v in category_acc.items() if v[1]]
        source_files = DocumentFile.query.filter_by(check_id=check.id).order_by(DocumentFile.id.asc()).all()
        selected_ids = json_loads(check.selected_standard_ids_json, default=[])
        selected_standards = Standard.query.filter(Standard.id.in_(selected_ids)).all() if selected_ids else []
        committee_assignments = CommitteeAssignment.query.filter_by(check_id=check.id).all() if session['role'] == 'admin' else []
        committee_review = CommitteeReview.query.filter_by(check_id=check.id, committee_user_id=session.get('user_id')).first() if session['role'] == 'committee' else None
        committee_reviews = CommitteeReview.query.filter_by(check_id=check.id).order_by(CommitteeReview.updated_at.desc()).all()
        framework_by_code = {x.code: x for x in selected_standards}
        grouped_assessment = {}
        for item in compliance_results:
            code = item.get('standard') or item.get('standard_code') or 'OTHER'
            grouped_assessment.setdefault(code, []).append(item)
        return render_template('user/check_detail.html', check=check, test_suite=check.test_suite, standard_summary=standard_summary,
                               compliance_results=compliance_results, kg_summary=kg_summary, gemini_summary=gemini_summary, local_model_summary=local_model_summary,
                               category_summary=category_summary, maturity_distribution=maturity_distribution, grouped_assessment=grouped_assessment,
                               selected_standards=selected_standards, framework_by_code=framework_by_code, source_files=source_files,
                               committee_assignments=committee_assignments, committee_review=committee_review, committee_reviews=committee_reviews)

    @app.route('/check/<int:check_id>/run-compliance', methods=['GET', 'POST'])
    @login_required(role='user')
    def run_compliance(check_id):
        check = DocumentCheck.query.get_or_404(check_id)
        if ap.EDIT not in ap.check_permissions(check):
            return denied('document_check', check.id, ap.EDIT)
        if request.method == 'GET' and check.compliance_results_json:
            # Reloading a page must not resend documents to a model. Re-run requires POST.
            return redirect(url_for('view_check', check_id=check.id))
        selected_ids = json_loads(check.selected_standard_ids_json, default=[])
        graph = build_knowledge_graph(db.session, selected_ids)
        source_files = DocumentFile.query.filter_by(check_id=check.id).order_by(DocumentFile.id.asc()).all()
        if source_files:
            analysis_text = combine_documents_for_analysis(source_files, json_loads)
        else:
            # Backward compatibility for V12 assessments created before multi-file support.
            analysis_text = check.extracted_text or ''
        retrieved_items = retrieve_relevant_items(graph, analysis_text, top_k=50)
        evidence_map = build_evidence_map(source_files, graph, json_loads) if source_files else {}
        classification = (check.data_classification or 'open').lower()
        if classification not in ('open', 'confidential'):
            flash('Invalid document classification. Assessment was not sent.', 'danger')
            return redirect(url_for('view_check', check_id=check.id))
        is_open = classification == 'open'
        provider = 'gemini' if is_open else 'local_model'
        enabled = gemini_enabled if is_open else local_model_enabled
        scorer = score_with_gemini if is_open else score_with_local_model
        if not enabled():
            flash('Gemini requires GEMINI_API_KEY and GEMINI_MODEL.' if is_open else 'Assessment requires LOCAL_MODEL_API_URL.', 'danger')
            return redirect(url_for('view_check', check_id=check.id))
        # Same gate as the domain engine, also on every re-run (retry). No fallback to another provider.
        gated = source_files or [model_gate.LegacyText(check)]
        allowed, reasons = model_gate.authorize(gated, provider, check, ap.assessment_for_check(check))
        if not allowed:
            model_gate.log_block('document_check', check.id, provider, reasons)
            check.processing_provider = provider + '_blocked'
            db.session.commit()
            flash('ไม่ส่งเอกสารให้โมเดล: ' + ' · '.join(reasons), 'danger')
            return redirect(url_for('view_check', check_id=check.id))
        model_result = scorer(analysis_text, retrieved_items, evidence_map=evidence_map)
        if is_open:
            check.gemini_summary_json = json_dumps(model_result or {'used': False})
            check.local_model_summary_json = json_dumps({'used': False, 'reason': 'open_uses_gemini'})
        else:
            check.local_model_summary_json = json_dumps(model_result or {'used': False})
            check.gemini_summary_json = json_dumps({'used': False, 'reason': 'confidential_uses_local_model'})
        if not model_result or model_result.get('used') is False:
            error_detail = (model_result or {}).get('error') or 'Model API returned no result.'
            flash(f'{provider} could not complete the assessment: {error_detail}', 'danger')
            check.processing_provider = provider + '_error'
            db.session.commit()
            return redirect(url_for('view_check', check_id=check.id))
        result = run_hybrid_compliance(analysis_text, graph, model_result, provider='gemini+kg' if is_open else 'local+kg', evidence_map=evidence_map)
        check.processing_provider = provider
        check.compliance_results_json = json_dumps(result['all_items'])
        check.standard_summary_json = json_dumps(result['per_standard'])
        check.compliance_score = result['overall_percent']
        check.maturity_level = result['maturity_level']
        check.kg_summary_json = json_dumps(retrieved_items)
        report_path = os.path.join(app.config['REPORT_FOLDER'], f'system_report_{check.id}.pdf')
        try:
            generate_system_report(report_path, {
                'filename': check.original_filename, 'filenames': [x.original_filename for x in source_files], 'template_name': check.test_suite.name,
                'compliance_score': check.compliance_score,
                'maturity_level': check.maturity_level, 'recommendations': check.thai_recommendations,
                'data_classification': check.data_classification, 'processing_provider': check.processing_provider,
                'standard_summary': result['per_standard'], 'compliance_items': result['all_items'], 'kg_summary': retrieved_items,
            })
            check.report_pdf_path = report_path
        except Exception as e:
            check.report_pdf_path = None
            flash(f'Report generation warning: {e}', 'warning')
        db.session.commit()
        write_log('run_hybrid_compliance', 'document_check', check.id, f"score={check.compliance_score}; classification={check.data_classification}; provider={check.processing_provider}")
        flash(f'Compliance assessment finished using {check.processing_provider}.', 'success')
        return redirect(url_for('view_check', check_id=check.id))


    @app.route('/check/<int:check_id>/comparison')
    @login_required()
    def assessment_comparison(check_id):
        check = DocumentCheck.query.get_or_404(check_id)
        if ap.VIEW not in ap.check_permissions(check):
            return denied('document_check', check.id, ap.VIEW)

        system_items = json_loads(check.compliance_results_json, default=[])
        system_by_code = {str(x.get('item_code')): x for x in system_items if x.get('item_code')}
        reviews = CommitteeReview.query.filter_by(check_id=check.id).order_by(CommitteeReview.updated_at.asc()).all()
        review_rows = []
        committee_by_item = {}
        for review in reviews:
            scores = json_loads(review.scores_json, default={})
            review_rows.append({'review': review, 'scores': scores})
            for payload in scores.values():
                code = str(payload.get('item_code') or '')
                if not code:
                    continue
                try:
                    sc = float(payload.get('score', 0))
                except Exception:
                    sc = 0.0
                committee_by_item.setdefault(code, []).append({
                    'score': sc,
                    'comment': payload.get('comment', ''),
                    'committee_name': review.committee.full_name if review.committee else 'Committee'
                })

        comparison_rows = []
        for sys_item in system_items:
            code = str(sys_item.get('item_code') or '')
            committee_entries = committee_by_item.get(code, [])
            committee_avg = round(sum(x['score'] for x in committee_entries) / len(committee_entries), 2) if committee_entries else None
            try:
                system_score = float(sys_item.get('score', 0))
            except Exception:
                system_score = 0.0
            comparison_rows.append({
                'item_code': code,
                'title': sys_item.get('title', ''),
                'standard': sys_item.get('standard') or sys_item.get('standard_code') or '-',
                'system_score': system_score,
                'committee_avg': committee_avg,
                'delta': round(committee_avg - system_score, 2) if committee_avg is not None else None,
                'committee_entries': committee_entries,
                'system_reason': sys_item.get('reason', ''),
                'system_gap': sys_item.get('gap', ''),
                'system_recommendation': sys_item.get('recommendation', ''),
                'evidence': sys_item.get('evidence', []),
            })
        return render_template('user/comparison.html', check=check, system_items=system_items,
                               reviews=reviews, review_rows=review_rows, comparison_rows=comparison_rows)

    @app.route('/check/<int:check_id>/report')
    @login_required()
    def download_system_report(check_id):
        check = DocumentCheck.query.get_or_404(check_id)
        if ap.EXPORT not in ap.check_permissions(check):
            return denied('document_check', check.id, ap.EXPORT)
        if not check.report_pdf_path or not os.path.exists(check.report_pdf_path):
            flash('System report not found.', 'warning')
            return redirect(url_for('view_check', check_id=check.id))
        write_log('report_download', 'document_check', check.id, 'system report pdf')
        return send_file(check.report_pdf_path, as_attachment=True)

    @app.route('/check/<int:check_id>/source/<int:file_id>')
    @login_required()
    def source_pdf(check_id, file_id):
        check = DocumentCheck.query.get_or_404(check_id)
        doc_file = DocumentFile.query.filter_by(id=file_id, check_id=check.id).first_or_404()
        if ap.READ_SOURCE not in ap.check_permissions(check):
            return denied('document_file', doc_file.id, ap.READ_SOURCE)
        full_path = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], doc_file.stored_filename))
        upload_root = os.path.abspath(app.config['UPLOAD_FOLDER'])
        if os.path.commonpath([full_path, upload_root]) != upload_root or not os.path.exists(full_path):
            flash('Source PDF not found.', 'warning')
            return redirect(url_for('view_check', check_id=check.id))
        write_log('file_open', 'document_file', doc_file.id, f'check={check.id}')
        return send_file(full_path, mimetype='application/pdf', download_name=doc_file.original_filename)

    # Committee routes
    @app.route('/committee')
    @login_required(role='committee')
    def committee_dashboard():
        assignments = CommitteeAssignment.query.filter_by(committee_user_id=session['user_id'], is_active=True).order_by(CommitteeAssignment.created_at.desc()).all()
        return render_template('committee/dashboard.html', assignments=assignments)

    @app.route('/committee/check/<int:check_id>/review', methods=['GET', 'POST'])
    @login_required(role='committee')
    def committee_review(check_id):
        assignment = CommitteeAssignment.query.filter_by(check_id=check_id, committee_user_id=session['user_id'], is_active=True).first_or_404()
        check = assignment.check
        selected_ids = json_loads(check.selected_standard_ids_json, default=[])
        standards = Standard.query.filter(Standard.id.in_(selected_ids)).all() if selected_ids else []
        all_items = []
        for s in standards:
            items = StandardItem.query.filter_by(standard_id=s.id, is_enabled=True).order_by(StandardItem.order_index.asc()).all()
            for i in items:
                all_items.append({'standard': s.code, 'item_id': i.id, 'item_code': i.item_code, 'title': i.title})
        source_files = DocumentFile.query.filter_by(check_id=check.id).order_by(DocumentFile.id.asc()).all()
        # System assessment is shown side-by-side with the committee assessment.
        compliance_results = json_loads(check.compliance_results_json, default=[])
        system_by_code = {str(x.get('item_code')): x for x in compliance_results if x.get('item_code')}

        review = CommitteeReview.query.filter_by(check_id=check.id, committee_user_id=session['user_id']).first()
        existing_scores = json_loads(review.scores_json, default={}) if review else {}
        if request.method == 'POST':
            score_map = {}
            for item in all_items:
                item_key = str(item['item_id'])
                score_map[item_key] = {
                    'item_code': item['item_code'], 'title': item['title'], 'standard': item['standard'],
                    'score': max(0, min(5, request.form.get(f"score_{item['item_id']}", type=int, default=0))),
                    'comment': request.form.get(f"comment_{item['item_id']}", '').strip()[:10000]
                }
            comments = request.form.get('comments', '')
            if not review:
                review = CommitteeReview(assignment_id=assignment.id, committee_user_id=session['user_id'], check_id=check.id)
                db.session.add(review)
            review.scores_json = json_dumps(score_map)
            review.comments = comments
            report_path = os.path.join(app.config['REPORT_FOLDER'], f'committee_report_{check.id}_{session["user_id"]}.pdf')
            try:
                generate_committee_report(report_path, {
                    'committee_name': session['full_name'], 'filename': check.original_filename,
                    'system_score': check.compliance_score, 'committee_scores': list(score_map.values()), 'comments': comments,
                })
                review.report_pdf_path = report_path
            except Exception as e:
                flash(f'Committee report warning: {e}', 'warning')
            db.session.commit()
            write_log('save_committee_review', 'committee_review', review.id, f'check={check.id}')
            flash('Committee review saved.', 'success')
            return redirect(url_for('committee_review', check_id=check.id))
        # Graph data for committee: system score versus committee score by standard.
        graph_rows = []
        for std in standards:
            std_items = [x for x in all_items if x['standard'] == std.code]
            sys_scores, com_scores = [], []
            for x in std_items:
                sys_item = system_by_code.get(x['item_code'], {})
                try: sys_scores.append(float(sys_item.get('score', 0)))
                except Exception: sys_scores.append(0.0)
                ex = existing_scores.get(str(x['item_id']), {})
                try: com_scores.append(float(ex.get('score', sys_item.get('score', 0))))
                except Exception: com_scores.append(0.0)
            if std_items:
                graph_rows.append({
                    'code': std.code,
                    'system': round(sum(sys_scores)/len(sys_scores), 2),
                    'committee': round(sum(com_scores)/len(com_scores), 2)
                })
        return render_template('committee/review.html', assignment=assignment, check=check, source_files=source_files, all_items=all_items,
                               existing_scores=existing_scores, review=review, system_by_code=system_by_code,
                               graph_rows=graph_rows)

    @app.route('/committee/check/<int:check_id>/source-pdf')
    @login_required(role='committee')
    def committee_source_pdf(check_id):
        assignment = CommitteeAssignment.query.filter_by(
            check_id=check_id, committee_user_id=session['user_id'], is_active=True
        ).first_or_404()
        check = assignment.check
        if ap.READ_SOURCE not in ap.check_permissions(check):
            return denied('document_check', check.id, ap.READ_SOURCE)
        full_path = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], check.stored_filename))
        upload_root = os.path.abspath(app.config['UPLOAD_FOLDER'])
        if os.path.commonpath([full_path, upload_root]) != upload_root or not os.path.exists(full_path):
            flash('Original PDF not found.', 'warning')
            return redirect(url_for('committee_review', check_id=check_id))
        write_log('file_open', 'document_check', check.id, 'committee original pdf')
        return send_file(full_path, mimetype='application/pdf', as_attachment=False,
                         download_name=check.original_filename)

    @app.route('/committee/review/<int:check_id>/report')
    @login_required(role='committee')
    def download_committee_report(check_id):
        review = CommitteeReview.query.filter_by(check_id=check_id, committee_user_id=session['user_id']).first_or_404()
        if not review.report_pdf_path or not os.path.exists(review.report_pdf_path):
            flash('Committee report not found.', 'warning')
            return redirect(url_for('committee_review', check_id=check_id))
        write_log('report_download', 'committee_review', review.id, f'check={check_id}')
        return send_file(review.report_pdf_path, as_attachment=True)

    # Admin routes
    @app.route('/admin')
    @login_required(role='admin')
    def admin_dashboard():
        stats = {'users': User.query.filter_by(role='user').count(), 'committee': User.query.filter_by(role='committee').count(), 'templates': Template.query.count(), 'checks': DocumentCheck.query.count()}
        recent_checks = DocumentCheck.query.order_by(DocumentCheck.created_at.desc()).limit(12).all()
        return render_template('admin/dashboard.html', stats=stats, recent_checks=recent_checks)

    @app.route('/admin/templates', methods=['GET', 'POST'])
    @login_required(role='admin')
    def admin_templates():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name:
                flash('Test Suite name is required.', 'warning')
                return redirect(url_for('admin_templates'))
            pass_threshold = request.form.get('pass_threshold', type=float, default=70.0)
            description = request.form.get('description', '').strip()
            sections = [x.strip() for x in request.form.get('sections_text', '').splitlines() if x.strip()]
            framework_codes = request.form.getlist('framework_codes')
            db.session.add(Template(
                name=name, description=description, prompt_structure='\n'.join(sections),
                sections_json=json_dumps(sections), applicable_framework_codes_json=json_dumps(framework_codes),
                pass_threshold=pass_threshold, is_enabled=True,
                display_order=(db.session.query(db.func.max(Template.display_order)).scalar() or 0) + 1
            ))
            db.session.commit()
            flash('Test Suite created.', 'success')
            return redirect(url_for('admin_templates'))
        templates = Template.query.order_by(Template.display_order, Template.name, Template.id).all()
        session.setdefault('suite_order_token', secrets.token_urlsafe(32))
        standards = Standard.query.filter_by(is_enabled=True).order_by(Standard.source_type.asc(), Standard.code.asc()).all()
        template_framework_map = {str(t.id): json_loads(t.applicable_framework_codes_json, default=[]) for t in templates}
        return render_template('admin/templates.html', templates=templates, standards=standards, template_framework_map=template_framework_map)

    @app.route('/admin/templates/reorder', methods=['POST'])
    @login_required(role='admin')
    def reorder_test_suites():
        token = request.headers.get('X-Suite-Order-Token', '')
        expected = session.get('suite_order_token')
        if not expected or not secrets.compare_digest(token, expected):
            return jsonify(error='เซสชันไม่ตรงกัน กรุณารีเฟรชหน้าแล้วลองใหม่'), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='Invalid order payload'), 400
        order, previous = payload.get('order'), payload.get('previous_order')
        if (not isinstance(order, list) or not isinstance(previous, list)
                or any(type(value) is not int for value in order + previous)
                or len(order) != len(set(order))):
            return jsonify(error='Invalid Test Suite identifiers'), 400
        try:
            suites = Template.query.order_by(Template.display_order, Template.name, Template.id).with_for_update().all()
            current = [suite.id for suite in suites]
            if previous != current or len(order) != len(current) or set(order) != set(current):
                db.session.rollback()
                return jsonify(error='รายการหรือลำดับถูกเปลี่ยนแล้ว กรุณารีเฟรชก่อนจัดลำดับใหม่'), 409
            positions = {suite_id: position for position, suite_id in enumerate(order, 1)}
            for suite in suites:
                suite.display_order = positions[suite.id]
            db.session.add(AuditLog(user_id=session['user_id'], actor_email=session.get('email'),
                                    action='reorder_test_suites', target_type='test_suite',
                                    detail=json_dumps({'before': current, 'after': order})))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Unable to save Test Suite order')
            return jsonify(error='บันทึกลำดับไม่ได้ กรุณาลองใหม่'), 500
        return jsonify(order=order)

    @app.route('/admin/templates/extract', methods=['POST'])
    @login_required(role='admin')
    def extract_template_from_doc():
        file = request.files.get('template_doc')
        name = request.form.get('template_name', '').strip() or 'Extracted Test Suite'
        threshold = request.form.get('pass_threshold', type=float, default=70.0)
        if not file or file.filename == '':
            flash('Please upload a PDF.', 'warning')
            return redirect(url_for('admin_templates'))
        stored, path = save_uploaded_file(file, app.config['UPLOAD_FOLDER'])
        text = extract_text_from_pdf(path)
        headings = extract_headings_from_text(text)
        framework_codes = request.form.getlist('framework_codes')
        db.session.add(Template(
            name=name, description='Test Suite structure extracted from uploaded reference document.',
            prompt_structure='\n'.join(headings), sections_json=json_dumps(headings),
            applicable_framework_codes_json=json_dumps(framework_codes),
            pass_threshold=threshold, is_enabled=True,
            display_order=(db.session.query(db.func.max(Template.display_order)).scalar() or 0) + 1
        ))
        db.session.commit()
        flash('Test Suite extracted from document.', 'success')
        return redirect(url_for('admin_templates'))

    @app.route('/admin/templates/<int:template_id>/status', methods=['POST'])
    @login_required(role='admin')
    def set_template_status(template_id):
        token = session.get('suite_order_token', '')
        if not token or not secrets.compare_digest(token, request.form.get('token', '')):
            return 'Invalid token. Refresh the page and try again.', 403
        value = request.form.get('is_enabled')
        if value not in ('0', '1'):
            return 'Invalid status', 400
        suite = Template.query.get_or_404(template_id)
        suite.is_enabled = value == '1'
        db.session.commit()
        flash('เปิดใช้งาน Test Suite แล้ว' if suite.is_enabled else 'ปิดใช้งาน Test Suite แล้ว', 'success')
        return redirect(url_for('admin_templates', suite=template_id))

    @app.route('/admin/templates/<int:template_id>/update', methods=['POST'])
    @login_required(role='admin')
    def update_template(template_id):
        t = Template.query.get_or_404(template_id)
        t.pass_threshold = request.form.get('pass_threshold', type=float, default=t.pass_threshold)
        if 'is_enabled' in request.form:
            if request.form['is_enabled'] not in ('0', '1'):
                return 'Invalid status', 400
            t.is_enabled = request.form['is_enabled'] == '1'
        if 'description' in request.form:
            t.description = request.form.get('description', '').strip()
        if 'framework_codes_present' in request.form:
            t.applicable_framework_codes_json = json_dumps(request.form.getlist('framework_codes'))
        db.session.commit()
        flash('Test Suite updated.', 'success')
        return redirect(url_for('admin_templates', suite=template_id))

    @app.route('/admin/templates/<int:template_id>/delete', methods=['POST'])
    @login_required(role='admin')
    def delete_template(template_id):
        t = Template.query.get_or_404(template_id)
        db.session.delete(t)
        db.session.commit()
        flash('Test Suite deleted.', 'success')
        return redirect(url_for('admin_templates'))

    @app.route('/admin/standards', methods=['GET', 'POST'])
    @login_required(role='admin')
    def admin_standards():
        if request.method == 'POST':
            db.session.add(Standard(
                code=request.form['code'].strip(), name=request.form['name'].strip(),
                description=request.form.get('description', '').strip(),
                source_type=request.form.get('source_type', 'international_standard').strip(),
                jurisdiction=request.form.get('jurisdiction', '').strip(),
                publisher=request.form.get('publisher', '').strip(),
                reference_url=request.form.get('reference_url', '').strip(),
                is_enabled=True
            ))
            db.session.commit()
            flash('Standard created.', 'success')
            return redirect(url_for('admin_standards'))
        standards = Standard.query.order_by(Standard.code.asc()).all()
        return render_template('admin/standards.html', standards=standards)

    @app.route('/admin/standards/<int:standard_id>/toggle', methods=['POST'])
    @login_required(role='admin')
    def toggle_standard(standard_id):
        s = Standard.query.get_or_404(standard_id)
        s.is_enabled = not s.is_enabled
        db.session.commit()
        return redirect(url_for('admin_standards'))

    @app.route('/admin/standards/<int:standard_id>/delete', methods=['POST'])
    @login_required(role='admin')
    def delete_standard(standard_id):
        s = Standard.query.get_or_404(standard_id)
        db.session.delete(s)
        db.session.commit()
        return redirect(url_for('admin_standards'))

    @app.route('/admin/standards/<int:standard_id>/items', methods=['GET', 'POST'])
    @login_required(role='admin')
    def manage_standard_items(standard_id):
        standard = Standard.query.get_or_404(standard_id)
        if request.method == 'POST':
            next_idx = (db.session.query(db.func.max(StandardItem.order_index)).filter_by(standard_id=standard.id).scalar() or 0) + 1
            db.session.add(StandardItem(
                standard_id=standard.id, item_code=request.form['item_code'].strip(), category=request.form.get('category', '').strip(),
                title=request.form['title'].strip(), keywords_json=json_dumps([x.strip() for x in request.form.get('keywords', '').split(',') if x.strip()]),
                weight=request.form.get('weight', type=float, default=1.0), order_index=next_idx, is_enabled=True
            ))
            db.session.commit()
            flash('Item added.', 'success')
            return redirect(url_for('manage_standard_items', standard_id=standard.id))
        items = StandardItem.query.filter_by(standard_id=standard.id).order_by(StandardItem.order_index.asc()).all()
        return render_template('admin/standard_items.html', standard=standard, items=items)

    @app.route('/admin/standard-items/<int:item_id>/update', methods=['POST'])
    @login_required(role='admin')
    def update_standard_item(item_id):
        i = StandardItem.query.get_or_404(item_id)
        i.item_code = request.form.get('item_code', i.item_code).strip()
        i.category = request.form.get('category', i.category or '').strip()
        i.title = request.form.get('title', i.title).strip()
        i.keywords_json = json_dumps([x.strip() for x in request.form.get('keywords', '').split(',') if x.strip()])
        i.weight = request.form.get('weight', type=float, default=i.weight)
        i.is_enabled = request.form.get('is_enabled') == '1'
        db.session.commit()
        flash('Item updated.', 'success')
        return redirect(url_for('manage_standard_items', standard_id=i.standard_id))

    @app.route('/admin/standard-items/<int:item_id>/delete', methods=['POST'])
    @login_required(role='admin')
    def delete_standard_item(item_id):
        i = StandardItem.query.get_or_404(item_id)
        sid = i.standard_id
        db.session.delete(i)
        db.session.commit()
        return redirect(url_for('manage_standard_items', standard_id=sid))

    @app.route('/admin/standards/<int:standard_id>/reorder', methods=['POST'])
    @login_required(role='admin')
    def reorder_standard_items(standard_id):
        order = request.get_json(force=True).get('order', [])
        for idx, item_id in enumerate(order, start=1):
            item = StandardItem.query.get(int(item_id))
            if item and item.standard_id == standard_id:
                item.order_index = idx
        db.session.commit()
        return jsonify({'success': True})

    @app.route('/admin/users')
    @login_required(role='admin')
    def admin_users():
        users = User.query.order_by(User.role.asc(), User.created_at.desc()).all()
        return render_template('admin/users.html', users=users)

    @app.route('/admin/committee/create', methods=['POST'])
    @login_required(role='admin')
    def create_committee():
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        organization = request.form.get('organization', '').strip()
        password = request.form.get('password', '').strip()
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'warning')
            return redirect(url_for('admin_users'))
        db.session.add(User(full_name=full_name, email=email, organization=organization,
                            password_hash=generate_password_hash(password), password_plain=None,
                            role='committee', is_active=True))
        db.session.commit()
        write_log('permission_account_create', 'user', None, f'committee={email}')
        flash('Committee account created.', 'success')
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
    @login_required(role='admin')
    def toggle_user(user_id):
        user = User.query.get_or_404(user_id)
        if user.role == 'admin':
            flash('Cannot disable admin here.', 'warning')
            return redirect(url_for('admin_users'))
        user.is_active = not user.is_active
        db.session.commit()
        write_log('permission_account_' + ('enable' if user.is_active else 'disable'), 'user', user.id, user.email)
        return redirect(url_for('admin_users'))

    @app.route('/admin/assignments', methods=['GET', 'POST'])
    @login_required(role='admin')
    def admin_assignments():
        if request.method == 'POST':
            check_id = request.form.get('check_id', type=int)
            committee_user_id = request.form.get('committee_user_id', type=int)
            existing = CommitteeAssignment.query.filter_by(check_id=check_id, committee_user_id=committee_user_id).first()
            if existing:
                existing.is_active, existing.revoked_at, existing.revoked_by = True, None, None
            else:
                db.session.add(CommitteeAssignment(check_id=check_id, committee_user_id=committee_user_id, is_active=True, assigned_by=session['user_id']))
            db.session.commit()
            write_log('permission_review_grant', 'document_check', check_id, f'committee_user={committee_user_id}')
            flash('Committee assigned.', 'success')
            return redirect(url_for('admin_assignments'))
        checks = DocumentCheck.query.order_by(DocumentCheck.created_at.desc()).all()
        committees = User.query.filter_by(role='committee').order_by(User.full_name.asc()).all()
        assignments = CommitteeAssignment.query.order_by(CommitteeAssignment.created_at.desc()).all()
        return render_template('admin/assignments.html', checks=checks, committees=committees, assignments=assignments)

    @app.route('/admin/assignments/<int:assignment_id>/toggle', methods=['POST'])
    @login_required(role='admin')
    def toggle_assignment(assignment_id):
        a = CommitteeAssignment.query.get_or_404(assignment_id)
        a.is_active = not a.is_active
        if not a.is_active:
            a.revoked_at, a.revoked_by = __import__('datetime').datetime.utcnow(), session['user_id']
        db.session.commit()
        write_log('permission_review_' + ('grant' if a.is_active else 'revoke'), 'document_check', a.check_id, f'committee_user={a.committee_user_id}')
        return redirect(url_for('admin_assignments'))

    @app.route('/admin/logs')
    @login_required(role='admin')
    def admin_logs():
        logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
        return render_template('admin/logs.html', logs=logs)

    return app

app = create_app()

def assert_pilot_schema():
    """Refuse to start on a database that has not run migrate_mhesi_pilot.py, instead of failing on the first query."""
    from sqlalchemy import inspect as sa_inspect
    with app.app_context():
        inspector = sa_inspect(db.engine)
        tables = set(inspector.get_table_names())
        if 'domain_assessments' in tables and 'workflow_status' not in {c['name'] for c in inspector.get_columns('domain_assessments')}:
            raise SystemExit('Database is missing the pilot columns. Back it up, then run: python migrate_mhesi_pilot.py')


if __name__ == '__main__':
    assert_safe_runtime()
    assert_pilot_schema()
    with app.app_context():
        db.create_all()
    app.run(host=Config.APP_HOST, port=Config.APP_PORT, debug=Config.DEBUG)
