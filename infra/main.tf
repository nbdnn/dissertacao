terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# NOTE: Set your default project ID and region when running 'terraform apply'
# export TF_VAR_project_id="your-gcp-project"
variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "The region to deploy resources (e.g., us-central1)"
  type        = string
  default     = "us-central1"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ==============================================================================
# 1. API Enablement
# ==============================================================================
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",             # For Cloud Run / Cloud Run Jobs
    "pubsub.googleapis.com",          # For Asynchronous Messaging
    "cloudscheduler.googleapis.com",  # For Triggering the Poller
    "eventarc.googleapis.com",        # For Event Routing
    "aiplatform.googleapis.com",      # Vertex AI (for Vizier / ADK Agent)
    "firestore.googleapis.com",       # Fast tracking of Matrix State/Historical TLEs
    "cloudfunctions.googleapis.com",  # For the Pub/Sub to Job routing
    "cloudbuild.googleapis.com"
  ])
  project = var.project_id
  service = each.key
  disable_on_destroy = false
}

# ==============================================================================
# 2. Identity & Access (Service Account)
# ==============================================================================
resource "google_service_account" "matrix_sa" {
  account_id   = "orbit-matrix-runner"
  display_name = "Service Account for MapReduce Orbit Calculations"
  project      = var.project_id
  depends_on   = [google_project_service.apis]
}

# ==============================================================================
# 3. Messaging (Pub/Sub)
# ==============================================================================
# Topic that receives messages whenever a satellite TLE changes.
resource "google_pubsub_topic" "tle_updates" {
  name       = "tle-updates"
  project    = var.project_id
  depends_on = [google_project_service.apis]
}

# ==============================================================================
# 4. Ingestion / Polling (Cloud Scheduler + Cloud Run)
# ==============================================================================
# Microservice that polls Space-Track every few minutes, detects diffs, and publishes.
resource "google_cloud_run_v2_service" "tle_ingestor" {
  name     = "tle-ingestor"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.matrix_sa.email
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello" # Placeholder: Deploy your Python script here
      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.tle_updates.id
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# Pings the ingestor continuously
resource "google_cloud_scheduler_job" "ingestor_trigger" {
  name             = "trigger-tle-ingestor"
  description      = "Ping the ingestor to diff the catalog from Space-Track"
  schedule         = "*/5 * * * *" # Every 5 minutes
  time_zone        = "UTC"
  project          = var.project_id
  region           = var.region

  http_target {
    http_method = "POST"
    uri         = google_cloud_run_v2_service.tle_ingestor.uri
    oidc_token {
      service_account_email = google_service_account.matrix_sa.email
    }
  }
  depends_on = [google_project_service.apis]
}

# ==============================================================================
# 5. The MapReduce Workers (Cloud Run Jobs - Heavily Parallelized)
# ==============================================================================
# Cloud Run Jobs natively support "Array Tasks". We define 300 parallel tasks.
# Each task container runs your Orekit script, computing 1 updated satellite vs a chunk of 100 catalog satellites.
resource "google_cloud_run_v2_job" "collision_matrix_job" {
  name     = "collision-matrix-solver"
  location = var.region
  project  = var.project_id

  template {
    parallelism = 300 # Execute up to 300 instances perfectly concurrently
    task_count  = 300 # The CLOUD_RUN_TASK_INDEX env var tells the script which chunk of 100 to process

    template {
      service_account = google_service_account.matrix_sa.email
      timeout         = "600s" # Hard timeout (should finish in <30s mathematically)
      
      containers {
        image = "us-docker.pkg.dev/cloudrun/container/hello" # Placeholder: Deploy Orekit Worker here
        resources {
          limits = {
            cpu    = "2"      # High mathematical CPU throughput
            memory = "2Gi"    # Enough memory to load Orekit models and chunk in RAM
          }
        }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# ==============================================================================
# 6. Database (Firestore for State/Aggregation)
# ==============================================================================
# Used to store the 'Marked Satellites' and aggregating the responses from the 300 workers
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = "nam5" # Multi-region US for high availability
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.apis]
}
