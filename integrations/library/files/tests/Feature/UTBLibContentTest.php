<?php

namespace Tests\Feature;

use Illuminate\Support\Facades\Http;
use Tests\Concerns\BuildsAdminControlPlane;
use Tests\TestCase;

class UTBLibContentTest extends TestCase
{
    use BuildsAdminControlPlane;

    protected function setUp(): void
    {
        putenv('UTBLIB_CONTENT_ENABLED=true');
        $_ENV['UTBLIB_CONTENT_ENABLED'] = $_SERVER['UTBLIB_CONTENT_ENABLED'] = 'true';
        parent::setUp();
        $this->setUpAdminControlPlane();
        config(['utblib_catalog.url' => 'http://utblib.test']);
        Http::preventStrayRequests();
    }

    protected function tearDown(): void
    {
        parent::tearDown();
        putenv('UTBLIB_CONTENT_ENABLED');
        unset($_ENV['UTBLIB_CONTENT_ENABLED'], $_SERVER['UTBLIB_CONTENT_ENABLED']);
    }

    private function row(string $kind): array
    {
        return ['id' => 42, 'kind' => $kind, 'slug' => 'remote-'.$kind, 'published_at' => now()->subDay()->toIso8601String(),
            'assets' => ['image' => ['url' => '/image', 'size' => 10, 'name' => 'image.jpg'], 'pdf' => ['url' => '/pdf', 'size' => 100, 'name' => 'document.pdf']],
            'data' => ['translations' => ['ru' => ['title' => 'UTBLib '.$kind, 'description' => 'Описание материала', 'body' => 'Текст материала\n\n<script>alert(1)</script>', 'instructions' => 'Инструкция', 'venue' => 'Библиотека']],
                'featured' => true, 'category' => '', 'news_type' => 'announcement', 'starts_at' => now()->addDays(3)->toIso8601String(),
                'ends_at' => now()->addDays(3)->addHour()->toIso8601String(), 'registration_url' => 'https://example.org/register', 'online_url' => '', 'organizer' => 'Библиотека',
                'url' => 'https://example.org/resource', 'provider' => 'Поставщик', 'resource_type' => 'open_access', 'access_type' => 'open', 'expires_on' => '',
                'audiences' => [], 'content_types' => ['scientific_articles'],
                'authors' => ['Тестовый автор'], 'keywords' => ['Наука'], 'work_type' => 'scientific_article', 'year' => 2026,
                'language' => 'ru', 'faculty' => 'Технологии', 'department' => 'Химия', 'educational_programme' => '6B01', 'supervisor' => '',
                'udc_code' => '54', 'university' => 'КазУТБ', 'doi' => '', 'source' => 'Автор', 'rights_holder' => 'Автор', 'licence_type' => 'CC BY',
                'access_policy' => 'full_public', 'embargo_until' => null]];
    }

    private function fakeContent(?callable $modify = null): void
    {
        Http::fake(function ($request) use ($modify) {
            $path = parse_url($request->url(), PHP_URL_PATH);
            if ($path === '/api/public/v1/catalog') return Http::response(['data' => [], 'meta' => ['total' => 9882, 'total_copies' => 1828]]);
            if (str_contains($path, '/content-assets/')) return Http::response('%PDF-1.4\n%%EOF', 200, ['Content-Type' => 'application/pdf']);
            if (preg_match('~/content/(resources|repository|news|events)(?:/([^/]+))?$~D', $path, $m)) {
                $row = $this->row($m[1]);
                if ($modify) $row = $modify($row);
                if (isset($m[2])) return in_array($m[2], [$row['slug'], 'utblib-42']) ? Http::response(['data' => $row]) : Http::response([], 404);
                return Http::response(['data' => [$row], 'meta' => ['total' => 1, 'last_page' => 1, 'page' => 1]]);
            }
            return Http::response([], 404);
        });
    }

    public function test_original_templates_receive_content_and_translations(): void
    {
        $this->fakeContent();
        foreach (['resources', 'repository', 'news', 'events'] as $kind) {
            $this->get('/'.$kind.'?lang=ru')->assertOk()->assertSee('UTBLib '.$kind);
        }
        $this->get('/resources/remote-resources?lang=ru')->assertOk()->assertSee('UTBLib resources');
        $this->get('/repository/utblib-42?lang=ru')->assertOk()->assertSee('UTBLib repository')->assertSee('/repository/utblib-42/download', false);
        $this->get('/news/remote-news?lang=kk')->assertOk()->assertSee('UTBLib news')->assertDontSee('<script>alert(1)</script>', false);
        $this->get('/events/remote-events?lang=en')->assertOk()->assertSee('UTBLib events');
        $this->get('/?lang=ru')->assertOk()->assertSee('UTBLib news')->assertSee('UTBLib repository');
    }

    public function test_public_actions_use_remote_identifiers_and_authorisation(): void
    {
        $this->fakeContent();
        $this->get('/resources/utblib-42/open')->assertRedirect('https://example.org/resource');
        $this->post('/utblib-content/events/utblib-42/register')->assertRedirect('https://example.org/register');
        $this->get('/repository/utblib-42/download')->assertOk()->assertHeader('Content-Type', 'application/pdf')->assertHeader('Cache-Control', 'no-store, private');
        $this->get('/repository/42')->assertNotFound();
        $this->get('/resources/42/open')->assertNotFound();
        $this->get('/news/missing')->assertNotFound();
    }

    public function test_closed_files_and_campus_resources_cannot_be_opened_by_guest(): void
    {
        config(['digital_access.campus_ranges' => ['10.0.0.0/8']]);
        $this->fakeContent(function ($row) {
            $row['data']['access_policy'] = 'metadata_only'; $row['assets']['pdf']['url'] = null;
            $row['data']['access_type'] = 'campus'; return $row;
        });
        $this->get('/repository/utblib-42?lang=ru')->assertOk()->assertDontSee('/repository/utblib-42/download', false);
        $this->get('/repository/utblib-42/download')->assertNotFound();
        $this->get('/resources/utblib-42/open')->assertForbidden();
    }

    public function test_empty_and_unavailable_upstream_never_show_legacy_content(): void
    {
        Http::fake(['*' => Http::response(['data' => [], 'meta' => ['total' => 0, 'last_page' => 1, 'page' => 1]])]);
        foreach (['resources', 'repository', 'news', 'events'] as $kind) $this->get('/'.$kind.'?lang=ru')->assertOk()->assertDontSee('UTBLib '.$kind);
    }

    public function test_unavailable_upstream_returns_503(): void
    {
        Http::fake(['*' => Http::response([], 503)]);
        $this->get('/news?lang=ru')->assertStatus(503)->assertDontSee('utblib.test');
    }

    public function test_repository_filters_and_live_statistics(): void
    {
        $this->fakeContent();
        $this->get('/repository?'.http_build_query(['lang' => 'ru', 'faculty' => 'Другой факультет']))->assertOk()->assertDontSee('UTBLib repository');
        $this->get('/repository?'.http_build_query(['lang' => 'ru', 'author' => 'Тестовый автор']))->assertOk()->assertSee('UTBLib repository');
        $stats = app(\App\Services\Library\PublicPortalStatistics::class)->snapshot();
        $this->assertSame(9882, $stats['catalog_titles']);
        $this->assertSame(1, $stats['published_resources']);
        $this->assertSame(1, $stats['published_events']);
    }
}
