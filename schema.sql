DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS committee_reviews;
DROP TABLE IF EXISTS committee_assignments;
DROP TABLE IF EXISTS document_files;
DROP TABLE IF EXISTS document_checks;
DROP TABLE IF EXISTS standard_items;
DROP TABLE IF EXISTS standards;
DROP TABLE IF EXISTS templates;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(255) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  organization VARCHAR(255) NULL,
  password_hash VARCHAR(255) NOT NULL,
  password_plain VARCHAR(255) NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'user',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  auth_provider VARCHAR(30) NOT NULL DEFAULT 'local',
  external_subject VARCHAR(255) NULL UNIQUE,
  thaid_reference_hash VARCHAR(64) NULL,
  last_login_at DATETIME NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_users_email (email),
  INDEX idx_users_external_subject (external_subject),
  INDEX idx_users_thaid_hash (thaid_reference_hash)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE templates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL UNIQUE,
  description TEXT NULL,
  prompt_structure TEXT NOT NULL,
  sections_json LONGTEXT NOT NULL,
  applicable_framework_codes_json LONGTEXT NULL,
  pass_threshold FLOAT NOT NULL DEFAULT 70,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE standards (
  id INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(100) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  source_type VARCHAR(50) NOT NULL DEFAULT 'international_standard',
  jurisdiction VARCHAR(100) NULL,
  publisher VARCHAR(255) NULL,
  reference_url VARCHAR(500) NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE standard_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  standard_id INT NOT NULL,
  item_code VARCHAR(100) NOT NULL,
  category VARCHAR(255) NULL,
  title TEXT NOT NULL,
  keywords_json LONGTEXT NOT NULL,
  weight FLOAT NOT NULL DEFAULT 1,
  order_index INT NOT NULL DEFAULT 0,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_std_item_standard FOREIGN KEY (standard_id) REFERENCES standards(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE document_checks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  template_id INT NOT NULL,
  original_filename VARCHAR(255) NOT NULL,
  stored_filename VARCHAR(255) NOT NULL,
  selected_standard_ids_json LONGTEXT NOT NULL,
  data_classification VARCHAR(30) NOT NULL DEFAULT 'open',
  processing_provider VARCHAR(50) NOT NULL DEFAULT 'pending',
  extracted_text LONGTEXT NULL,
  extracted_headings_json LONGTEXT NULL,
  matched_sections_json LONGTEXT NULL,
  missing_sections_json LONGTEXT NULL,
  section_scores_json LONGTEXT NULL,
  completeness_score FLOAT NOT NULL DEFAULT 0,
  completeness_passed TINYINT(1) NOT NULL DEFAULT 0,
  thai_recommendations LONGTEXT NULL,
  compliance_results_json LONGTEXT NULL,
  compliance_score FLOAT NOT NULL DEFAULT 0,
  maturity_level VARCHAR(50) NULL,
  standard_summary_json LONGTEXT NULL,
  kg_summary_json LONGTEXT NULL,
  gemini_summary_json LONGTEXT NULL,
  local_model_summary_json LONGTEXT NULL,
  report_pdf_path VARCHAR(500) NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_doc_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_doc_template FOREIGN KEY (template_id) REFERENCES templates(id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;


CREATE TABLE document_files (
  id INT AUTO_INCREMENT PRIMARY KEY,
  check_id INT NOT NULL,
  original_filename VARCHAR(255) NOT NULL,
  stored_filename VARCHAR(255) NOT NULL,
  page_count INT NOT NULL DEFAULT 0,
  extracted_text LONGTEXT NULL,
  pages_json LONGTEXT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_document_files_check (check_id),
  CONSTRAINT fk_document_file_check FOREIGN KEY (check_id) REFERENCES document_checks(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE committee_assignments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  check_id INT NOT NULL,
  committee_user_id INT NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_assignment_check FOREIGN KEY (check_id) REFERENCES document_checks(id) ON DELETE CASCADE,
  CONSTRAINT fk_assignment_committee FOREIGN KEY (committee_user_id) REFERENCES users(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE committee_reviews (
  id INT AUTO_INCREMENT PRIMARY KEY,
  assignment_id INT NOT NULL,
  committee_user_id INT NOT NULL,
  check_id INT NOT NULL,
  scores_json LONGTEXT NULL,
  comments LONGTEXT NULL,
  report_pdf_path VARCHAR(500) NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_review_assignment FOREIGN KEY (assignment_id) REFERENCES committee_assignments(id) ON DELETE CASCADE,
  CONSTRAINT fk_review_committee FOREIGN KEY (committee_user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_review_check FOREIGN KEY (check_id) REFERENCES document_checks(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE audit_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NULL,
  actor_email VARCHAR(255) NULL,
  action VARCHAR(255) NOT NULL,
  target_type VARCHAR(100) NULL,
  target_id VARCHAR(100) NULL,
  detail LONGTEXT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
