const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "https://worksphere-lead-generation.onrender.com/api";

async function apiRequest(endpoint, options = {}) {
  const response = await fetch(
    `${API_BASE_URL}${endpoint}`,
    {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {})
      },
      ...options
    }
  );

  const responseText = await response.text();
  let data = null;

  if (responseText.trim()) {
    try {
      data = JSON.parse(responseText);
    } catch {
      if (response.ok) {
        throw new Error(`Server returned an invalid response (HTTP ${response.status}).`);
      }
    }
  }

  if (!response.ok) {
    throw new Error(
      data?.details
        ? `${data.error || "Request failed"}: ${data.details}`
        : data?.error || `Request failed (HTTP ${response.status}).`
    );
  }

  if (data === null) {
    throw new Error(`Server returned an empty response (HTTP ${response.status}).`);
  }

  return data;
}


// --------------------------------------------------
// Companies
// --------------------------------------------------

export async function getCompanies() {
  const data = await apiRequest("/companies");
  if (!Array.isArray(data?.companies)) {
    throw new Error("The companies API returned an unexpected response.");
  }
  return data;
}


// --------------------------------------------------
// Company Intelligence
// --------------------------------------------------

export async function getCompanyIntelligence(companyName) {
  const data = await apiRequest(
    `/company-intelligence/${encodeURIComponent(companyName)}`
  );
  if (!data?.company || !Array.isArray(data.reports) ||
      !Array.isArray(data.evidence) || !Array.isArray(data.processing_runs)) {
    throw new Error("The company details API returned an unexpected response.");
  }
  return data;
}

export async function getCompanyNews(companyId, limit = 50) {
  const data = await apiRequest(
    `/company-intelligence/${encodeURIComponent(companyId)}/news?limit=${encodeURIComponent(limit)}`
  );
  if (!Array.isArray(data?.articles) || typeof data?.state !== "string") {
    throw new Error("The company news API returned an unexpected response.");
  }
  return data;
}

export async function ingestCompanyNews(companyId, days = 30) {
  return apiRequest(
    `/company-intelligence/${encodeURIComponent(companyId)}/news/ingest?days=${encodeURIComponent(days)}`,
    { method: "POST" }
  );
}

export async function processAnnualReport(reportId) {
  return apiRequest(
    `/reports/${encodeURIComponent(reportId)}/process`,
    {
      method: "POST",
    }
  );
}

export async function ingestCompanyAnnualReport(companyId) {
  return apiRequest(
    `/reports/companies/${encodeURIComponent(companyId)}/ingest`,
    { method: "POST" }
  );
}


// --------------------------------------------------
// Existing backend endpoints
// --------------------------------------------------

export async function getDocuments() {
  return apiRequest("/documents");
}


export async function getEvidence(validationStatus) {
  const query = validationStatus
    ? `?validation_status=${encodeURIComponent(
        validationStatus
      )}`
    : "";

  return apiRequest(`/evidence${query}`);
}


export async function getDocumentEvidence(
  documentId,
  validationStatus
) {
  const query = validationStatus
    ? `?validation_status=${encodeURIComponent(
        validationStatus
      )}`
    : "";

  return apiRequest(
    `/documents/${documentId}/evidence${query}`
  );
}


export async function extractEvidence(documentId) {
  return apiRequest(
    `/documents/${documentId}/extract-evidence`,
    {
      method: "POST"
    }
  );
}


export async function validateEvidence(documentId) {
  return apiRequest(
    `/documents/${documentId}/validate-evidence`,
    {
      method: "POST"
    }
  );
}


export async function updateCompanySalesStage(companyId, salesStage) {
  const data = await apiRequest(
    `/companies/${encodeURIComponent(companyId)}/sales-stage`,
    {
      method: "PATCH",
      body: JSON.stringify({
        sales_stage: salesStage,
      }),
    }
  );
  if (!["suspect", "prospect"].includes(data?.company?.sales_stage)) {
    throw new Error("The sales stage API did not confirm the persisted stage.");
  }
  return data;
}
