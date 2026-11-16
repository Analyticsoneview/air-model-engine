output "vpc_id" { value = aws_vpc.air.id }
output "public_subnet_ids" { value = aws_subnet.public[*].id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "alb_dns_name" { value = aws_lb.air.dns_name }
output "alb_zone_id" { value = aws_lb.air.zone_id }
output "ecr_backend_repository_url" { value = aws_ecr_repository.backend.repository_url }
output "ecr_pwa_repository_url" { value = aws_ecr_repository.pwa.repository_url }
output "rds_endpoint" { value = aws_db_instance.air.address }
output "redis_primary_endpoint" { value = aws_elasticache_replication_group.air.primary_endpoint_address }
output "rabbitmq_endpoint" { value = aws_mq_broker.air.instances[0].endpoints[0] }
output "efs_file_system_id" { value = aws_efs_file_system.air.id }
output "s3_bucket_name" { value = aws_s3_bucket.air.bucket }
output "ecs_cluster_name" { value = aws_ecs_cluster.air.name }
output "deployment_services_enabled" { value = var.deploy_services }
output "api_service_name" { value = var.deploy_services ? aws_ecs_service.api[0].name : null }
output "worker_service_name" { value = var.deploy_services ? aws_ecs_service.worker[0].name : null }
output "pwa_service_name" { value = var.deploy_services ? aws_ecs_service.pwa[0].name : null }
output "runtime_secret_arns" {
  value = {
    database = aws_secretsmanager_secret.postgres.arn
    redis    = aws_secretsmanager_secret.redis.arn
    rabbitmq = aws_secretsmanager_secret.rabbitmq.arn
    jwt      = aws_secretsmanager_secret.jwt.arn
  }
}
