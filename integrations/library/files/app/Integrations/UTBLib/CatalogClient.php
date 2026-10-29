<?php

namespace App\Integrations\UTBLib;

use Illuminate\Support\Facades\Http;
use Symfony\Component\HttpKernel\Exception\HttpException;
use Throwable;

class CatalogClient
{
    public function get(string $path, array $query = [], bool $allowNotFound = false): ?array
    {
        $url = rtrim((string) config('utblib_catalog.url'), '/');
        if (! preg_match('~^https?://~i', $url)) {
            throw new HttpException(503, 'The catalogue is temporarily unavailable.');
        }
        try {
            $response = Http::acceptJson()->connectTimeout(3)
                ->timeout((int) config('utblib_catalog.timeout', 10))
                ->withoutRedirecting()->get($url.'/api/public/v1/'.$path,
                    array_filter($query, static fn ($value) => $value !== null && $value !== ''));
            if ($allowNotFound && $response->status() === 404) {
                return null;
            }
            if ($response->successful() && is_array($response->json())) {
                $result = $response->json();
                if ($path === 'catalog') {
                    $result['data'] = array_map(self::present(...), $result['data'] ?? []);
                } elseif (str_starts_with($path, 'books/') && isset($result['data'])) {
                    $result['data'] = self::present($result['data'], true);
                }
                return $result;
            }
        } catch (Throwable) {
            // Do not expose internal addresses or fall back to unrelated legacy record IDs.
        }
        throw new HttpException(503, 'The catalogue is temporarily unavailable.');
    }

    private static function present(array $book, bool $detail = false): array
    {
        // The existing book template expects text, including the publication year.
        $book['publicationYear'] = isset($book['publicationYear']) ? (string) $book['publicationYear'] : null;
        $locale = request()->query('lang', app()->getLocale());
        $locale = in_array($locale, ['ru', 'kk', 'en'], true) ? $locale : app()->getLocale();
        $code = \App\Support\PublicCatalogLanguage::normalize($book['language']['code'] ?? 'other');
        // Catalogue JS translates codes using its selected UI language; detail expects a label.
        $book['language']['label'] = $detail ? (string) __('common.languages.'.$code, [], $locale) : '';
        return $book;
    }
}
