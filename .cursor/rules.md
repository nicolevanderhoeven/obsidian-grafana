# Project Rules for Obsidian-Grafana Monitoring System

## 1. Security and Sensitive Information Management

### Environment Variables and Configuration
- **No Hardcoded Credentials**: Never hardcode passwords, API keys, or sensitive configuration in source code
- **Use Environment Variables**: All sensitive data must be stored in environment variables or configuration files excluded from version control
- **Configuration Files**: Use `config.yaml.example` as a template and keep actual `config.yaml` in `.gitignore`
- **Path Management**: Use environment variables for user-specific paths (e.g., `OBSIDIAN_VAULT_PATH`, `OUTPUT_DIR`)
- **Docker Secrets**: For production deployments, use Docker secrets or environment files for sensitive data

### Examples of What to Avoid
```yaml
# ❌ BAD - Hardcoded sensitive data
grafana_password: "admin123"
vault_path: "/Users/nic/obsidian-vault"

# ✅ GOOD - Environment variables
grafana_password: "${GRAFANA_PASSWORD}"
vault_path: "${OBSIDIAN_VAULT_PATH}"
```

## 2. Data Privacy and Offline Operations

### Local-Only Processing
- **No External Data Transmission**: All data processing must occur locally on the user's machine
- **Offline Dependencies**: Only use libraries and tools that operate entirely offline
- **No Cloud Services**: Do not integrate with external APIs or cloud services for data processing
- **Local Storage**: All logs, metrics, and dashboards must be stored locally

### Data Handling
- **User Data Protection**: Obsidian vault data never leaves the local environment
- **Log Retention**: Implement local log rotation and cleanup policies
- **Backup Strategy**: Provide local backup mechanisms for Grafana dashboards and configurations

## 3. Label Management and Cardinality Control

### Label Approval Process
- **Express Approval Required**: New Loki labels require explicit approval before implementation
- **Documentation**: All labels must be documented with their purpose and expected cardinality
- **Review Process**: Label additions must go through code review

### High Cardinality Prevention
- **Label Limits**: 
  - Maximum 10 unique values per label
  - Avoid dynamic labels (timestamps, user IDs, random strings)
  - Use static, categorical labels only
- **Frontmatter Label Strategy**:
  - Limit frontmatter fields to low-cardinality values
  - Truncate long values to prevent high cardinality
  - Use whitelist approach for allowed frontmatter fields
- **Monitoring**: Implement cardinality monitoring and alerting

### Label Naming Conventions
```yaml
# ✅ GOOD - Low cardinality labels
frontmatter_type: "NPC" | "PC" | "audio" | "document"
frontmatter_status: "active" | "inactive" | "draft"
tags: "research" | "meeting" | "project"

# ❌ BAD - High cardinality labels
note_name: "unique-note-name-123"  # Too many unique values
timestamp: "2024-01-15T10:30:00Z"  # Dynamic values
user_id: "user-12345"              # Dynamic values
```

## 4. Code Quality and Testing

### Testing Requirements
- **Unit Tests**: Write unit tests for all Python functions, especially parsing logic
- **Integration Tests**: Test the complete pipeline from parsing to Grafana visualization
- **Configuration Tests**: Validate configuration file parsing and environment variable handling
- **LogQL Query Tests**: Test LogQL queries against sample data

### Code Standards
- **Error Handling**: Implement comprehensive error handling for file operations and parsing
- **Logging**: Use structured logging with appropriate log levels
- **Documentation**: Document all functions, classes, and configuration options
- **Type Hints**: Use Python type hints for better code maintainability

## 5. Performance and Resource Management

### Resource Limits
- **Memory Usage**: Monitor memory consumption during large vault processing
- **File System**: Implement efficient file scanning to avoid excessive I/O
- **Docker Resources**: Set appropriate resource limits for Docker containers
- **Log Rotation**: Implement automatic log rotation to prevent disk space issues

### Optimization Guidelines
- **Incremental Processing**: Only process changed files when possible
- **Batch Operations**: Process files in batches to reduce overhead
- **Caching**: Implement caching for frequently accessed metadata
- **Async Operations**: Use async processing where appropriate

## 6. Monitoring and Observability

### Health Checks
- **Service Health**: Implement health checks for all Docker services
- **Data Pipeline**: Monitor the complete data flow from parsing to visualization
- **Error Tracking**: Track and alert on parsing errors and service failures
- **Performance Metrics**: Monitor processing time and resource usage

### Alerting
- **Service Down**: Alert when any service becomes unavailable
- **High Cardinality**: Alert when label cardinality exceeds thresholds
- **Parse Errors**: Alert on parsing failures or data quality issues
- **Resource Usage**: Alert on high memory or disk usage

## 7. Documentation and Maintenance

### Documentation Requirements
- **Setup Instructions**: Keep setup instructions current and comprehensive
- **Configuration Guide**: Document all configuration options and their effects
- **Troubleshooting**: Maintain troubleshooting guides for common issues
- **API Documentation**: Document any APIs or interfaces

### Maintenance Tasks
- **Regular Updates**: Keep dependencies updated and secure
- **Configuration Review**: Regularly review and update configuration templates
- **Dashboard Maintenance**: Keep Grafana dashboards current and functional
- **Log Cleanup**: Implement automated log cleanup and archival

## 8. Production Considerations

### Security Hardening
- **Authentication**: Implement proper authentication for all services
- **Network Security**: Use proper networking and firewall rules
- **Data Encryption**: Encrypt sensitive data at rest and in transit
- **Access Control**: Implement proper access controls and permissions

### Scalability
- **Horizontal Scaling**: Design for horizontal scaling if needed
- **Data Partitioning**: Consider data partitioning strategies for large datasets
- **Load Balancing**: Implement load balancing for high availability
- **Backup Strategy**: Implement comprehensive backup and recovery procedures

## 9. Compliance and Governance

### Data Governance
- **Data Classification**: Classify data based on sensitivity and importance
- **Retention Policies**: Implement data retention and deletion policies
- **Audit Logging**: Maintain audit logs for all data access and modifications
- **Compliance**: Ensure compliance with relevant data protection regulations

### Change Management
- **Version Control**: Use proper version control practices
- **Change Approval**: Require approval for significant changes
- **Rollback Procedures**: Maintain rollback procedures for failed deployments
- **Testing Requirements**: Require testing before production deployment

## 10. Emergency Procedures

### Incident Response
- **Service Recovery**: Document procedures for recovering failed services
- **Data Recovery**: Implement data recovery procedures
- **Communication**: Define communication procedures for incidents
- **Escalation**: Define escalation procedures for critical issues

### Backup and Recovery
- **Regular Backups**: Implement regular backup procedures
- **Recovery Testing**: Regularly test recovery procedures
- **Disaster Recovery**: Maintain disaster recovery plans
- **Business Continuity**: Ensure business continuity during outages

---

## Enforcement

These rules are mandatory for all contributors and must be followed without exception. Regular audits will be conducted to ensure compliance, and violations will be addressed promptly.

For questions or clarifications about these rules, please refer to the project maintainers or create an issue in the project repository.
