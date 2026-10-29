<?php

namespace App\Integrations\UTBLib;

use Closure;
use Illuminate\Http\Request;

class RemoteCatalogBoundary
{
    public function handle(Request $request, Closure $next)
    {
        // The existing detail page probes the old digital library separately.
        // Remote record IDs must never be resolved against its document table.
        if ($request->isMethod('GET') && preg_match('~^api/v1/documents/utblib-\d+/digital-materials$~D', $request->path())) {
            return response()->json(['data' => [], 'meta' => ['total' => 0], 'success' => true]);
        }
        return $next($request);
    }
}
