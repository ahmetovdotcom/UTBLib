<?php

namespace App\Integrations\UTBLib;

use App\Models\User;

class BookDetailReadService extends \App\Services\Library\BookDetailReadService
{
    public function findByIdentifier(string $identifier, ?User $viewer = null): ?array
    {
        $result = app(CatalogClient::class)->get('books/'.rawurlencode($identifier), allowNotFound: true);
        return $result['data'] ?? null;
    }
}
