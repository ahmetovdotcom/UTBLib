<?php

return [
    'content_enabled' => env('UTBLIB_CONTENT_ENABLED', false),
    'enabled' => env('UTBLIB_CATALOG_ENABLED', false),
    // Server-to-server address. Never put a staff password or ADMIN_KEY here.
    'url' => env('UTBLIB_CATALOG_URL', ''),
    'timeout' => (int) env('UTBLIB_CATALOG_TIMEOUT', 10),
];
