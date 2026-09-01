import { createServer } from "node:http";

const jobs = new Map();
const port = Number(process.env.MOCK_AUDIT_ENGINE_PORT ?? 8010);

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

const server = createServer(async (request, response) => {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  const body = Buffer.concat(chunks);
  if (!request.headers.authorization || !request.headers["x-zorva-signature"]) {
    return json(response, 401, { error: "missing portal authentication" });
  }
  if (request.method === "POST" && request.url === "/encounters/upload/preview") {
    if (!body.includes(Buffer.from("CLM*PATIENT001"))) {
      return json(response, 200, { filename: "upload.edi", rows: [], error: "fixture claim missing" });
    }
    return json(response, 200, {
      filename: "sample-837P.edi",
      rows: [{
        encounter_id: "PATIENT001",
        patient_id: "123456789A",
        NPI: "1234567893",
        date_of_service: "2025-06-15",
        CPT_codes: ["99214"],
        diagnosis_codes: ["Z0000"],
        source_filename: "sample-837P.edi",
        source: "837p",
        errors: [],
      }],
    });
  }
  if (request.method === "POST" && request.url === "/api/audits") {
    const payload = JSON.parse(body.toString("utf8"));
    const jobId = `job-${payload.encounter_id}`;
    jobs.set(jobId, payload.encounter_id);
    return json(response, 202, {
      job_id: jobId,
      encounter_id: payload.encounter_id,
      status: "queued",
      status_url: `/encounters/upload/jobs/${jobId}`,
      dedup_hit: false,
    });
  }
  const jobMatch = request.url?.match(/^\/encounters\/upload\/jobs\/(.+)$/);
  if (request.method === "GET" && jobMatch && jobs.has(jobMatch[1])) {
    const encounterId = jobs.get(jobMatch[1]);
    return json(response, 200, {
      job_id: jobMatch[1],
      encounter_id: encounterId,
      status: "done",
      error: null,
      result: {
        summary: "Two mocked engine findings for portal contract verification.",
        findings: [
          {
            finding_id: "engine-finding-1",
            category: "code_mismatch",
            severity: 3,
            rule_id: "AHCIP-MOCK-1",
            suggested_code: "99215",
            quote: "Assessment and plan documented",
            explanation: "Documentation supports review of the billed service.",
          },
          {
            finding_id: "engine-finding-2",
            category: "documentation",
            severity: 2,
            rule_id: "AHCIP-MOCK-2",
            suggested_code: null,
            quote: "Follow-up plan",
            explanation: "Confirm the follow-up plan before submission.",
          },
        ],
      },
    });
  }
  return json(response, 404, { error: "not found" });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`mock audit engine listening on ${port}`);
});
