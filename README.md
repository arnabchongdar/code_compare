output "primary_api_endpoint" {
  value = aws_apigatewayv2_api.primary_api.api_endpoint
}

output "secondary_api_endpoint" {
  value = aws_apigatewayv2_api.secondary_api.api_endpoint
}

output "route53_dns" {
  value = "api.${var.domain_name}"
}
