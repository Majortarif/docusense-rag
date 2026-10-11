# Northbridge Analytics — IT, Security & Operations Policy Handbook

Document ID: POL-IT-001. Version 3.2. Effective date: 1 March 2026. Policy owner: Office of the CISO. Review cycle: annual.

## 1. Purpose and Scope

This handbook defines the mandatory IT, security and operational policies for all employees, contractors and temporary staff of Northbridge Analytics Ltd. ("the Company"). It applies to every production, staging and corporate system, whether it is hosted on-premises or with a cloud provider.

Where a team-level procedure conflicts with this handbook, this handbook takes precedence. Questions about how a policy should be interpreted must be sent to the Security & Compliance team at security@northbridge.example.

### 1.1 Definitions

- **Production system:** any system that stores or processes customer data or serves customer traffic.
- **Data owner:** the head of the business unit that is accountable for a dataset.
- **CISO:** the Chief Information Security Officer.
- **Incident commander:** the engineer who leads the response to an active incident.

## 2. Data Backup and Retention

### 2.1 Backup schedule

All production databases must be backed up automatically. A full backup is taken every Sunday at 01:00 UTC, and incremental backups are taken every 6 hours. Transaction logs for PostgreSQL clusters are archived continuously so that point-in-time recovery is possible.

Backup jobs are monitored by the Platform Engineering team. A backup job that fails twice in a row must raise an alert to the on-call engineer.

### 2.2 Retention periods

All primary database backups are retained for a rolling period of 30 calendar days. After 30 days, backups are automatically and permanently deleted by the backup system.

In addition, the first full backup of each month is kept as a monthly archive for 12 months. Year-end archives (the last full backup taken in December) are retained for 7 years to meet financial record-keeping obligations.

File-server and object-storage backups follow the same 30-day rolling retention, but no monthly archive is kept for them.

### 2.3 Backup storage and encryption

Backups are encrypted at rest with AES-256 and in transit with TLS 1.2 or higher. Encryption keys are managed in the Company's cloud key management service and are never stored alongside the backup data.

A copy of every backup is replicated to a secondary cloud region located at least 500 km from the primary region. Access to backup storage is limited to the Platform Engineering team and requires multi-factor authentication.

### 2.4 Recovery objectives and restore testing

The recovery point objective (RPO) for production databases is 6 hours, and the recovery time objective (RTO) is 4 hours.

Platform Engineering performs a full restore test of at least one production database every quarter and records the result in the restore-test register. A failed restore test must be treated as a SEV2 incident.

## 3. Access Control and Authentication

### 3.1 Multi-factor authentication

Multi-factor authentication (MFA) is mandatory for every account that can access Company systems, including email, source control and cloud consoles. Administrators must use a hardware security key (FIDO2) as their second factor. SMS codes are not permitted as a second factor for any account.

### 3.2 Passwords

Passwords must be at least 14 characters long. Passwords do not expire on a fixed schedule, but a password must be changed immediately if compromise is suspected. Staff must store work passwords only in the Company-provided password manager, and reusing a Company password on any external service is prohibited.

An account is locked for 15 minutes after 10 consecutive failed login attempts.

### 3.3 Least privilege and access reviews

Access is granted on a least-privilege basis: staff receive only the permissions that their current role requires. Data owners must review who has access to their systems every quarter and remove access that is no longer needed. Accounts that have been inactive for 60 days are disabled automatically.

### 3.4 Privileged access

Administrative access to production is granted just-in-time through the access portal for a maximum of 8 hours per request, and every request must reference an approved ticket. Shared administrator accounts are prohibited. Service account credentials must be rotated every 90 days.

### 3.5 Joiners, movers and leavers

New hires receive access only after they have signed the acceptable use agreement. When an employee changes role, access that the new role does not require must be removed within 5 business days.

When an employee leaves the Company, all of their access must be revoked within 24 hours of their last working day. For involuntary terminations, access must be revoked before the employee is notified.

## 4. Incident Response

### 4.1 Severity levels

- **SEV1 (Critical):** a complete outage of a customer-facing service, or a confirmed breach of Restricted data. SEV1 incidents must be acknowledged within 15 minutes, and status updates are posted every 30 minutes.
- **SEV2 (High):** a major degradation of a customer-facing service, or a suspected data breach. SEV2 incidents must be acknowledged within 30 minutes, and status updates are posted every hour.
- **SEV3 (Medium):** a minor degradation for which a workaround exists. SEV3 incidents must be acknowledged within 4 business hours.
- **SEV4 (Low):** a cosmetic issue with no customer impact. SEV4 issues are handled through the normal team backlog.

### 4.2 Reporting an incident

Anyone who suspects a security incident must report it immediately in the #incident-response channel or by calling the on-call security line. Do not try to investigate a suspected compromise on your own, and do not power off an affected machine, because doing so destroys forensic evidence.

### 4.3 On-call rotation

Each engineering team runs a weekly on-call rotation. The on-call handover happens every Monday at 10:00 local time. The on-call engineer must be able to respond to a page within 15 minutes.

### 4.4 Customer and regulator notification

When a personal data breach is confirmed, the Legal team must be informed within 24 hours. Affected customers and the relevant supervisory authority must be notified within 72 hours of the Company becoming aware of the breach.

### 4.5 Post-incident review

A blameless postmortem is required for every SEV1 and SEV2 incident. The postmortem must be published within 5 business days of the incident being resolved, and every action item must have a named owner and a due date.

## 5. Change Management

### 5.1 Code review and approvals

Every change to production code must be submitted as a pull request and approved by at least two engineers, one of whom must belong to the team that owns the service. All automated tests in the CI pipeline must pass before a change can be merged.

### 5.2 Deployment windows

Production deployments are allowed Monday to Thursday between 09:00 and 16:00 local time, and on Friday between 09:00 and 12:00. No production deployments are allowed on public holidays.

A company-wide change freeze applies every year from 20 December to 2 January. During the freeze, only emergency changes may be deployed.

### 5.3 Emergency changes

An emergency change that resolves a SEV1 or SEV2 incident may be deployed outside the deployment window if the incident commander approves it. Every emergency change must be documented and reviewed retrospectively within 2 business days.

### 5.4 Rollback

Every deployment must have a documented rollback plan. A deployment that causes an elevated error rate for more than 10 minutes must be rolled back before the team starts investigating the cause.

## 6. Data Classification and Handling

### 6.1 Classification levels

All Company data must be classified into one of four levels:

- **Public:** information approved for public release, such as marketing material and published documentation.
- **Internal:** information for employees only, such as internal announcements and this handbook.
- **Confidential:** sensitive business information, such as contracts, financial forecasts and source code.
- **Restricted:** the most sensitive data, such as customer personal data, payment data, credentials and encryption keys.

### 6.2 Handling rules

Restricted data must never be stored on laptops, removable media or personal cloud storage. Restricted data may only be sent by email when it is encrypted with the Company-approved encryption tool. Confidential data may be shared with external parties only under a signed non-disclosure agreement.

### 6.3 Customer data retention and deletion

Customer personal data is retained for the duration of the customer contract plus 2 years, after which it is deleted or irreversibly anonymised. A verified customer request to delete their personal data must be completed within 30 days of the request.

### 6.4 Test data

Production personal data must not be copied into development or testing environments. Teams must use synthetic or anonymised data for development and testing.

## 7. Logging and Monitoring

Application logs are kept in searchable storage for 90 days and then archived for a total retention of 1 year. Security audit logs, including authentication events and privileged access events, are retained for 2 years.

Logs must never contain passwords, access tokens, encryption keys or full payment card numbers. All servers must synchronise their clocks with the Company NTP service so that log timestamps can be correlated. Production alerts are routed to the on-call engineer of the owning team.

## 8. Endpoint and Remote Work Security

### 8.1 Company devices

Every Company laptop must have full-disk encryption and the Company endpoint protection agent enabled. Critical security updates must be installed within 7 days of release, and all other updates within 30 days. Screens must lock automatically after 5 minutes of inactivity.

### 8.2 Remote work

Staff working outside a Company office must connect through the Company VPN to reach internal systems. Public Wi-Fi may be used only while the VPN is connected. Working from outside your home country for more than 30 days requires prior approval from both HR and the Security & Compliance team.

### 8.3 Lost or stolen devices

A lost or stolen Company device must be reported to the IT Service Desk within 4 hours of discovering the loss. The IT Service Desk will remotely lock and wipe the device.

### 8.4 Personal devices

Personal mobile phones may access Company email and chat only through the managed mobile application. Personal laptops must never be used to access production systems.

## 9. Vendor and Third-Party Risk

A vendor that will store or process Confidential or Restricted data must pass a security assessment by the Security & Compliance team before a contract is signed. Such vendors must hold a current SOC 2 Type II report or an ISO 27001 certification.

Vendors are reassessed every year. A data processing agreement must be signed with every vendor that processes personal data on behalf of the Company.

## 10. Acceptable Use of Generative AI Tools

Staff may use only the generative AI tools listed in the approved tools catalogue on the intranet. Confidential or Restricted data must never be entered into a public generative AI tool.

Code produced with the help of an AI assistant must go through the same code review as any other change. Output from an AI tool must not be the sole basis for any decision about an individual, such as hiring, performance or customer eligibility.

## 11. Security Awareness Training

All staff must complete security awareness training within 30 days of joining the Company and every year after that. Phishing simulation exercises are run every quarter.

Staff who miss the annual training deadline have their access to non-essential systems suspended until the training is completed.

## 12. Policy Exceptions and Review

An exception to any policy in this handbook must be requested through the governance, risk and compliance (GRC) portal and approved by the CISO. An approved exception is valid for a maximum of 6 months and may be renewed once.

This handbook is reviewed every year by the Office of the CISO. Violations of these policies may lead to disciplinary action, up to and including termination of employment.
