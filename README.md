terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5.0"
}

# ---------- Providers ----------
provider "aws" {
  region = "us-east-1"
}

provider "aws" {
  alias  = "dr"
  region = "us-east-2"
}

# ---------- IAM Role ----------
resource "aws_iam_role" "lambda_role" {
  name = "dr-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ---------- Primary Lambda ----------
resource "aws_lambda_function" "primary" {
  function_name = "dr-primary"
  filename      = "lambda_primary.zip"
  handler       = "lambda_primary.lambda_handler"
  runtime       = "python3.12"
  role          = aws_iam_role.lambda_role.arn
}

# ---------- Secondary Lambda ----------
resource "aws_lambda_function" "secondary" {
  provider      = aws.dr
  function_name = "dr-secondary"
  filename      = "lambda_secondary.zip"
  handler       = "lambda_secondary.lambda_handler"
  runtime       = "python3.12"
  role          = aws_iam_role.lambda_role.arn
}

# ---------- API Gateways ----------
resource "aws_apigatewayv2_api" "primary_api" {
  name          = "dr-primary-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_api" "secondary_api" {
  provider      = aws.dr
  name          = "dr-secondary-api"
  protocol_type = "HTTP"
}

# Integrations
resource "aws_apigatewayv2_integration" "primary_integration" {
  api_id                 = aws_apigatewayv2_api.primary_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.primary.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "secondary_integration" {
  provider               = aws.dr
  api_id                 = aws_apigatewayv2_api.secondary_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.secondary.invoke_arn
  payload_format_version = "2.0"
}

# Routes
resource "aws_apigatewayv2_route" "primary_route" {
  api_id    = aws_apigatewayv2_api.primary_api.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.primary_integration.id}"
}

resource "aws_apigatewayv2_route" "secondary_route" {
  provider  = aws.dr
  api_id    = aws_apigatewayv2_api.secondary_api.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.secondary_integration.id}"
}

# Deployments
resource "aws_apigatewayv2_stage" "primary_stage" {
  api_id      = aws_apigatewayv2_api.primary_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_apigatewayv2_stage" "secondary_stage" {
  provider    = aws.dr
  api_id      = aws_apigatewayv2_api.secondary_api.id
  name        = "$default"
  auto_deploy = true
}

# Permissions for Lambda invoke
resource "aws_lambda_permission" "primary_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.primary.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.primary_api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "secondary_invoke" {
  provider      = aws.dr
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.secondary.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.secondary_api.execution_arn}/*/*"
}

# ---------- Route53 Setup ----------
# Replace with your actual domain
variable "domain_name" {
  default = "mydrdemo.com"
}

resource "aws_route53_zone" "main" {
  name = var.domain_name
}

# Health Check for Primary API
resource "aws_route53_health_check" "primary_health" {
  fqdn              = aws_apigatewayv2_api.primary_api.api_endpoint
  port              = 443
  type              = "HTTPS"
  resource_path     = "/"
  request_interval  = 30
  failure_threshold = 3
}

# Primary record (us-east-1)
resource "aws_route53_record" "primary" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "api.${var.domain_name}"
  type    = "CNAME"
  ttl     = 60
  records = [aws_apigatewayv2_api.primary_api.api_endpoint]
  set_identifier = "primary-us-east-1"
  failover_routing_policy {
    type = "PRIMARY"
  }
  health_check_id = aws_route53_health_check.primary_health.id
}

# Secondary record (us-east-2)
resource "aws_route53_record" "secondary" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "api.${var.domain_name}"
  type    = "CNAME"
  ttl     = 60
  records = [aws_apigatewayv2_api.secondary_api.api_endpoint]
  set_identifier = "secondary-us-east-2"
  failover_routing_policy {
    type = "SECONDARY"
  }
}
