<?php

namespace App\Integrations\UTBLib;

use Illuminate\Support\Collection;
use Symfony\Component\HttpFoundation\IpUtils;

class ExternalResourceService extends \App\Services\ExternalResourceService
{
    public function __construct(private ContentService $content) {}

    public function directory(array $filters = []): Collection
    {
        $rows = $this->content->all('resources')->map(fn ($r) => $this->present($r));
        foreach (['category', 'access_type', 'resource_type', 'status'] as $field) {
            if (! empty($filters[$field])) $rows = $rows->where($field, $filters[$field]);
        }
        foreach (['audience' => 'available_roles', 'content_type' => 'content_types'] as $filter => $field) {
            if (! empty($filters[$filter])) $rows = $rows->filter(fn ($r) => in_array($filters[$filter], $r[$field], true));
        }
        if (! empty($filters['access_scope'])) $rows = $rows->filter(fn ($r) => match ($filters['access_scope']) {
            'guest' => $r['guest_access'], 'authenticated' => $r['login_required'], 'campus' => $r['campus_only'], 'remote' => ! $r['campus_only'], default => true,
        });
        return $rows->values();
    }

    public function list(array $filters = []): Collection { return $this->directory($filters); }
    public function findBySlug(string $slug): ?array { return $this->findPublicBySlug($slug); }
    public function findPublicBySlug(string $slug): ?array
    {
        $row = app(CatalogClient::class)->get('content/resources/'.rawurlencode($slug), [], true);
        return $row ? $this->present($row['data']) : null;
    }

    public function present(array $row): array
    {
        $d = $row['data']; $type = $d['access_type'];
        $expired = ! empty($d['expires_on']) && $d['expires_on'] < now('Asia/Almaty')->toDateString();
        $onCampus = request()->ip() && IpUtils::checkIp(request()->ip(), (array) config('digital_access.campus_ranges', []));
        $canOpen = ! $expired && ($type === 'open' || ($type === 'campus' && $onCampus) || ($type === 'remote_auth' && request()->user()));
        return ['id' => 'utblib-'.$row['id'], 'slug' => $row['slug'],
            'title' => ContentService::translated($d['translations'], 'title'), 'provider' => $d['provider'],
            'description' => ContentService::translated($d['translations'], 'description'), 'resource_type' => $d['resource_type'],
            'access_type' => $type, 'status' => $expired ? 'expired' : 'active', 'term' => empty($d['expires_on']) ? ($d['resource_type'] === 'open_access' ? 'perpetual' : 'unknown') : 'dated',
            'expiry_date' => $d['expires_on'] ?: null, 'contract_starts_at' => null, 'contract_ends_at' => $d['expires_on'] ?: null,
            'url' => '/resources/utblib-'.$row['id'].'/open', 'detail_url' => '/resources/'.$row['slug'],
            'category' => $d['category'] ?: 'research_database',
            'notes' => ContentService::translated($d['translations'], 'instructions'),
            'access_instructions' => ContentService::translated($d['translations'], 'instructions'),
            'available_roles' => $d['audiences'] ?: ['guest', 'student', 'teacher', 'library_staff'],
            'content_types' => $d['content_types'], 'access_method' => ['open' => 'public_url', 'campus' => 'ip_based', 'remote_auth' => 'personal_account'][$type],
            'guest_access' => $type === 'open', 'campus_only' => $type === 'campus', 'login_required' => $type === 'remote_auth',
            'can_open' => (bool) $canOpen, 'access_denial' => $canOpen ? null : ($expired ? 'unavailable' : ($type === 'campus' ? 'campus' : 'sign_in')),
            'health_status' => 'unchecked', 'logo_path' => null, 'logo' => ContentService::asset($row, 'image')];
    }
}
