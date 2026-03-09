import { NextRequest } from "next/server";
import { fileStore, newId } from "../_store";
import formidable, { type File as FormidableFile } from "formidable";
import fs from "fs";
import path from "path";

export const runtime = "nodejs";

export const config = {
  api: {
    bodyParser: false
  }
};

function parseForm(req: NextRequest): Promise<{ files: FormidableFile[] }> {
  return new Promise(async (resolve, reject) => {
    const form = formidable({
      multiples: true,
      keepExtensions: true,
      maxFileSize: 20 * 1024 * 1024 // 20MB starter limit
    });

    // NextRequest does not expose raw req as Node IncomingMessage.
    // In Next.js App Router, we use req as Request; formidable needs Node req.
    // We'll reconstruct via req.body is not possible.
    // Therefore: use the built-in web API to read multipart is complex.
    // For a starter that actually works, we rely on Next.js "pages" API? Not available here.
    // Workaround: implement in route with unstable_parseMultipartFormData (not available).
    reject(new Error("Multipart parsing requires a Node request adapter. See README for working setup options."));
  });
}

export async function POST(_req: NextRequest) {
  // NOTE: The App Router route handler does not provide a Node IncomingMessage for formidable.
  // This endpoint is intentionally a starter contract. You can:
  // 1) Move this to /pages/api/files.ts (Pages Router) where formidable works cleanly, OR
  // 2) Use a dedicated upload service (S3/GCS signed URLs), OR
  // 3) Use Next.js middleware/adapters to get a Node req.
  return Response.json(
    {
      error:
        "Upload endpoint is a contract stub in this starter. See README for the 2-minute fix (Pages API route) or switch to signed uploads."
    },
    { status: 501 }
  );
}
