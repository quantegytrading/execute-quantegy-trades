terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.38.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4.2"
    }
  }
  required_version = "~> 1.2"
}

variable "eid" {
  default     = "binanceus"
  description = "Crypto Exchange"
}

variable "key" {
  default     = "key"
  description = "API key"
}

variable "secret" {
  default     = "secret"
  description = "API secret"
}


resource "null_resource" "install_python_dependencies" {
  provisioner "local-exec" {
    command = "bash ${path.module}/src/scripts/create_pkg.sh"

    environment = {
      source_code_path = "${path.module}/src"
      function_name = "quantegy_execute"
      runtime = "python3.10"
      path_cwd = "${path.module}"
    }
  }
}


data "archive_file" "function_zip" {
  source_dir  = "src"
  type        = "zip"
  output_path = "${path.module}/quantegy-execute.zip"
  depends_on = [ null_resource.install_python_dependencies ]
}

resource "aws_s3_object" "file_upload" {
  bucket = "quantegy-analyze-soak-us-east-1-lambda"
  key    = "quantegy-execute.zip"
  source = "quantegy-execute.zip"
  depends_on = [ data.archive_file.function_zip ]
}

resource "aws_lambda_function" "function" {
  s3_bucket                       = "quantegy-analyze-soak-us-east-1-lambda"
  s3_key                          = "quantegy-execute.zip"
  function_name                   = "quantegy-execute"
  handler                        = "conservative.main"
  runtime                        = "python3.10"
  timeout                        = 900
  memory_size                    = 128
  role                           = "arn:aws:iam::716418748259:role/quantegy-execute-soak-us-east-1-lambdaRole"
  environment {
    variables = {
      eid = var.eid
      key = var.key
      secret = var.secret
    }
  }
  depends_on = [ aws_s3_object.file_upload ]
}



