<?php

namespace Tests\Feature;

use App\Integrations\UTBLib\CatalogClient;
use App\Integrations\UTBLib\CatalogServiceProvider;
use App\Models\Catalog\BibliographicRecord;
use App\Services\Library\BookDetailReadService;
use App\Services\Library\CatalogReadService;
use Illuminate\Support\Facades\Http;
use Tests\Concerns\BuildsAdminControlPlane;
use Tests\TestCase;

class UTBLibCatalogTest extends TestCase
{
    use BuildsAdminControlPlane;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setUpAdminControlPlane();
        config(['utblib_catalog.enabled' => true, 'utblib_catalog.url' => 'http://utblib.test']);
        $provider = new CatalogServiceProvider($this->app);
        $provider->register();
        $provider->boot();
        Http::preventStrayRequests();
    }

    private function fakeCatalogue(): array
    {
        $book = [
            'source' => 'utblib', 'id' => 'utblib-42',
            'title' => ['display' => 'Кітап UTBLib', 'raw' => 'Кітап UTBLib', 'subtitle' => '', 'original' => 'Кітап UTBLib', 'isFallback' => false],
            'primaryAuthor' => 'Тестовый автор', 'authors' => [['name' => 'Тестовый автор']],
            'publisher' => ['name' => 'Издательство'], 'publicationYear' => 2024,
            'isbn' => ['raw' => '978-601-04-3364-9'], 'language' => ['code' => 'kk', 'raw' => 'kk', 'label' => ''],
            'annotation' => 'Қазақ тіліндегі сипаттама', 'resourceType' => 'book', 'coverPath' => null,
            'udc' => ['raw' => '54', 'display' => '54', 'description' => '', 'source' => 'udc'],
            'copies' => ['available' => 2, 'issued' => 1, 'total' => 3],
            'availability' => ['locations' => [], 'isAvailable' => true],
            'indicators' => ['availability' => 'available', 'format' => 'print', 'issueCount' => 5],
            'viewer' => ['canReserve' => false, 'reservationEligible' => false, 'activeLoan' => null],
        ];
        Http::fake([
            'utblib.test/api/public/v1/catalog*' => Http::response([
                'data' => [$book], 'meta' => ['total' => 1, 'page' => 1, 'per_page' => 24, 'total_pages' => 1, 'totalPages' => 1, 'total_copies' => 3],
            ]),
            'utblib.test/api/public/v1/facets*' => Http::response([
                'languages' => [['value' => 'kk', 'count' => 1]], 'udc' => [['value' => '54', 'count' => 1]],
                'years' => ['min' => 2024, 'max' => 2024], 'total' => 1,
            ]),
            'utblib.test/api/public/v1/books/*' => Http::response(['data' => $book, 'success' => true]),
        ]);
        return $book;
    }

    public function test_original_catalogue_and_detail_render_remote_records(): void
    {
        $this->fakeCatalogue();
        $this->get('/catalog?lang=ru')->assertOk()->assertSee('Кітап UTBLib')->assertSee('/book/utblib-42', false);
        $this->getJson('/api/v1/catalog-db?'.http_build_query(['q' => 'Кітап', 'language' => 'kk', 'available_only' => '1', 'limit' => 5]))
            ->assertOk()->assertJsonPath('data.0.id', 'utblib-42')->assertJsonPath('data.0.copies.issued', 1);
        Http::assertSent(function ($request): bool {
            parse_str(parse_url($request->url(), PHP_URL_QUERY) ?? '', $query);
            return str_contains($request->url(), '/catalog?') && ($query['q'] ?? '') === 'Кітап'
                && ($query['available_only'] ?? '') === 'true' && ($query['limit'] ?? '') === '5';
        });
        $this->get('/book/utblib-42?lang=ru')->assertOk()->assertSee('Кітап UTBLib')->assertDontSee('id="member-reserve-form"', false);
        $this->getJson('/api/v1/book-db/utblib-42?lang=ru')->assertOk()->assertJsonPath('data.viewer.canReserve', false)
            ->assertJsonPath('data.publicationYear', '2024')->assertJsonPath('data.language.label', __('common.languages.kk', [], 'ru'));
        $this->assertSame(0, BibliographicRecord::query()->count());
    }

    public function test_unavailable_upstream_does_not_fall_back_to_old_catalogue(): void
    {
        BibliographicRecord::factory()->create(['title' => 'LEGACY_WRONG_RECORD']);
        Http::fake(['*' => Http::response([], 503)]);
        $this->getJson('/api/v1/catalog-db')->assertStatus(503)->assertDontSee('LEGACY_WRONG_RECORD')->assertDontSee('utblib.test');
    }

    public function test_timeout_returns_generic_503(): void
    {
        Http::fake(['*' => fn () => throw new \Illuminate\Http\Client\ConnectionException('internal secret address')]);
        $this->getJson('/api/v1/catalog-db')->assertStatus(503)->assertDontSee('internal secret address');
    }

    public function test_missing_remote_record_and_legacy_digital_ids_are_not_mixed(): void
    {
        Http::fake(['*' => Http::response([], 404)]);
        $this->getJson('/api/v1/book-db/utblib-999')->assertNotFound();
        $this->getJson('/api/v1/documents/utblib-42/digital-materials')->assertOk()->assertJsonPath('data', []);
    }

    public function test_installation_is_opt_in(): void
    {
        config(['utblib_catalog.enabled' => false]);
        $this->app->bind(CatalogReadService::class, CatalogReadService::class);
        $this->app->bind(BookDetailReadService::class, BookDetailReadService::class);
        (new CatalogServiceProvider($this->app))->register();
        $this->assertSame(CatalogReadService::class, get_class(app(CatalogReadService::class)));
        Http::assertNothingSent();
    }
}
