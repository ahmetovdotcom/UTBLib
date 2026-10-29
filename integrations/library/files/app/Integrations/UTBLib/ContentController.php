<?php

namespace App\Integrations\UTBLib;

use Carbon\CarbonImmutable;
use Illuminate\Http\Request;
use Illuminate\Pagination\LengthAwarePaginator;
use Illuminate\Support\Facades\Http;

class ContentController
{
    public function __construct(private ContentService $content) {}

    private function value(Request $request, string $key, int $length = 200): string
    {
        $value = $request->query($key, '');
        return is_scalar($value) ? mb_substr(trim(preg_replace('/[\p{C}]+/u', ' ', (string) $value) ?? ''), 0, $length) : '';
    }

    private function search($rows, string $q)
    {
        return $q === '' ? $rows : $rows->filter(fn ($r) => str_contains(mb_strtolower(json_encode($r['data'], JSON_UNESCAPED_UNICODE)), mb_strtolower($q)));
    }

    public function newsIndex(Request $request)
    {
        $rows = $this->search($this->content->all('news'), $this->value($request, 'q'));
        foreach (['type' => 'news_type', 'category' => 'category'] as $filter => $field) {
            if ($v = $this->value($request, $filter)) $rows = $rows->filter(fn ($r) => $r['data'][$field] === $v);
        }
        foreach (['from', 'to'] as $key) {
            $v = $this->value($request, $key, 10);
            if (preg_match('/^\d{4}-\d{2}-\d{2}$/D', $v)) $rows = $rows->filter(fn ($r) => $key === 'from' ? substr($r['published_at'], 0, 10) >= $v : substr($r['published_at'], 0, 10) <= $v);
        }
        $total = $rows->count(); $last = max(1, (int) ceil($total/5));
        $page = min($last, max(1, (int) $this->value($request, 'page')));
        return view('news.index', ['activePage' => 'news', 'newsArticles' => $rows->values()->slice(($page-1)*5, 5)->map(fn ($r) => $this->content->article($r))->values()->all(),
            'currentPage' => $page, 'lastPage' => $last, 'newsTotal' => $total, 'showCanonicalHero' => $page === 1,
            'filterCategories' => collect(), 'newsTypes' => array_values(array_diff(\App\Models\News::TYPES, ['event', 'schedule']))]);
    }

    public function article(Request $request, string $kind, string $slug)
    {
        $row = $this->content->find($kind, $slug);
        $related = $this->content->all($kind)->reject(fn ($r) => $r['id'] === $row['id'])->take(3)->map(fn ($r) => $this->content->article($r))->values()->all();
        return view('news.show', ['activePage' => $kind, 'article' => $this->content->article($row), 'relatedArticles' => $related]);
    }

    public function eventsIndex(Request $request, array $events)
    {
        $locale = app()->getLocale();
        $rows = $this->search($this->content->all('events'), $this->value($request, 'q'))
            ->filter(fn ($r) => $this->content->upcoming($r))->sortBy('data.starts_at');
        if ($category = $this->value($request, 'category')) $rows = $rows->filter(fn ($r) => ($r['data']['category'] ?: 'event') === $category);
        $events['items'] = $rows->map(function ($r) use ($locale) {
            $d = $r['data']; $start = CarbonImmutable::parse($d['starts_at'])->timezone('Asia/Almaty');
            return ['slug' => $r['slug'], 'iso_date' => $start->toDateString(), 'featured' => $d['featured'], 'category_slug' => $d['category'] ?: 'event',
                'i18n' => [$locale => ['category' => __('news.types.event'), 'date_month_day' => $start->translatedFormat('d F'),
                    'date_year_time' => $start->translatedFormat('Y · H:i'), 'title' => ContentService::translated($d['translations'], 'title'),
                    'description' => ContentService::translated($d['translations'], 'description'), 'venue' => ContentService::translated($d['translations'], 'venue')]]];
        })->values()->all();
        return view('events.index', ['activePage' => 'events', 'events' => $events]);
    }

    public function resourceShow(Request $request, string $slug)
    {
        $service = app(ExternalResourceService::class); $resource = $service->findPublicBySlug($slug);
        abort_if($resource === null, 404);
        return view('resource-show', ['activePage' => 'resources', 'resource' => $resource,
            'categories' => $service->categories(), 'accessTypes' => $service->accessTypes()]);
    }

    public function resourceOpen(Request $request, string $externalResource)
    {
        abort_unless(preg_match('/^utblib-\d+$/D', $externalResource), 404);
        $row = $this->content->find('resources', $externalResource);
        $resource = app(ExternalResourceService::class)->present($row);
        abort_unless($resource['can_open'], 403);
        return redirect()->away($row['data']['url']);
    }

    public function register(Request $request, string $item)
    {
        abort_unless(preg_match('/^utblib-\d+$/D', $item), 404);
        $row = $this->content->find('events', $item);
        abort_unless($this->content->upcoming($row) && ! empty($row['data']['registration_url']), 404);
        return redirect()->away($row['data']['registration_url']);
    }

    public function index(Request $request)
    {
        $all = $this->content->all('repository'); $rows = $this->search($all, $search = $this->value($request, 'q'));
        $filters = ['work_type' => 'work_type', 'year' => 'year', 'language' => 'language', 'access' => 'access_policy', 'faculty' => 'faculty',
            'department' => 'department', 'educational_programme' => 'educational_programme', 'supervisor' => 'supervisor', 'udc' => 'udc_code'];
        $values = [];
        foreach ($filters as $query => $field) {
            $values[$query] = $v = $this->value($request, $query, 500);
            if ($v !== '') $rows = $rows->filter(fn ($r) => (string) ($r['data'][$field] ?? '') === $v);
        }
        $author = $this->value($request, 'author', 500);
        if ($author !== '') $rows = $rows->filter(fn ($r) => in_array($author, $r['data']['authors'], true));
        if ($values['access'] === 'full_public') $rows = $rows->filter(fn ($r) => ! empty($r['assets']['pdf']['url']));
        $total = $rows->count(); $page = max(1, (int) $this->value($request, 'page'));
        $items = new LengthAwarePaginator($rows->values()->slice(($page-1)*12,12)->map(fn ($r) => $this->content->record($r)), $total, 12, $page, ['path' => $request->url(), 'query' => $request->query()]);
        $facet = fn ($field) => $all->pluck('data.'.$field)->filter()->unique()->sort()->values();
        return view('repository.index', ['activePage' => 'repository', 'items' => $items,
            'facultyWorks' => ['stats' => ['works' => 0, 'authors' => 0, 'electronic' => 0, 'types' => []], 'works' => [], 'total' => 0, 'page' => 1, 'totalPages' => 1],
            'facultyFilters' => ['fw_q' => null, 'fw_type' => null, 'fw_format' => null, 'fw_page' => 1],
            'typeCounts' => $all->countBy('data.work_type'), 'years' => $facet('year')->sortDesc()->values(), 'publishedTotal' => $all->count(),
            'activeType' => $values['work_type'] ?: null, 'activeYear' => $values['year'] ?: null, 'activeLanguage' => $values['language'] ?: null,
            'activeAccess' => $values['access'] ?: null, 'activeFaculty' => $values['faculty'] ?: null, 'activeDepartment' => $values['department'] ?: null,
            'activeEducationalProgramme' => $values['educational_programme'] ?: null, 'activeAuthor' => $author ?: null,
            'activeSupervisor' => $values['supervisor'] ?: null, 'activeUdc' => $values['udc'] ?: null, 'activeSort' => 'latest', 'search' => $search ?: null,
            'facultyOptions' => $facet('faculty'), 'departmentOptions' => $facet('department'), 'educationalProgrammeOptions' => $facet('educational_programme'),
            'supervisorOptions' => $facet('supervisor'), 'udcOptions' => $facet('udc_code'), 'authorOptions' => $all->flatMap(fn ($r) => $r['data']['authors'])->unique()->sort()->values(), 'popularAvailable' => false]);
    }

    public function show(Request $request, string $item)
    {
        abort_unless(preg_match('/^utblib-\d+$/D', $item), 404);
        $row = $this->content->find('repository', $item); $model = $this->content->record($row);
        return response()->view('repository.show', ['activePage' => 'repository', 'item' => $model,
            'related' => $this->content->all('repository')->filter(fn ($r) => $r['id'] !== $row['id'] && $r['data']['work_type'] === $row['data']['work_type'])->take(2)->map(fn ($r) => $this->content->record($r)),
            'linkedNews' => collect(), 'canReadFull' => (bool) $model->file_url, 'hasFile' => isset($row['assets']['pdf']),
            'isAuthenticated' => $request->user() !== null, 'isWithdrawn' => false,
            'citation' => implode(', ', $model->authors).'. '.$model->title.'. '.$model->year.'. '.url('/repository/'.$item)]);
    }

    public function download(Request $request, string $item) { return $this->repositoryFile($request, $item, true); }
    public function view(Request $request, string $item) { return $this->repositoryFile($request, $item, false); }
    private function repositoryFile(Request $request, string $item, bool $download)
    {
        abort_unless(preg_match('/^utblib-(\d+)$/D', $item, $match), 404);
        $row = $this->content->find('repository', $item);
        abort_unless(! empty($row['assets']['pdf']['url']), 404);
        return $this->asset($request, $match[1], 'pdf', $download);
    }

    public function asset(Request $request, string $item, string $slot, bool $download = false)
    {
        abort_unless(ctype_digit($item) && in_array($slot, ['image', 'pdf'], true), 404);
        $base = rtrim((string) config('utblib_catalog.url'), '/');
        abort_unless(preg_match('~^https?://~i', $base), 503);
        try {
            $response = Http::connectTimeout(3)->timeout(30)->withoutRedirecting()->get($base.'/api/public/v1/content-assets/'.$item.'/'.$slot);
        } catch (\Throwable) { abort(503, 'Content is temporarily unavailable.'); }
        abort_if($response->status() === 404, 404);
        abort_unless($response->successful(), 503);
        $mime = $slot === 'pdf' ? 'application/pdf' : 'image/jpeg';
        abort_unless(str_starts_with($response->header('Content-Type'), $mime), 503);
        $headers = ['Content-Type' => $mime, 'Cache-Control' => 'no-store', 'X-Content-Type-Options' => 'nosniff',
            'Content-Security-Policy' => 'sandbox', 'Content-Disposition' => ($download ? 'attachment' : 'inline').'; filename="'.($slot === 'pdf' ? 'document.pdf' : 'image.jpg').'"'];
        return response($response->body(), 200, $headers);
    }
}
