<?php

namespace App\Integrations\UTBLib;

use Illuminate\Support\Fluent;
use Illuminate\Contracts\Routing\UrlRoutable;

/** Read-only view data: never an Eloquent model from the legacy database. */
class ContentRecord extends Fluent implements UrlRoutable
{
    public function getKey() { return $this->id; }
    public function getRouteKey() { return $this->id; }
    public function getRouteKeyName() { return 'id'; }
    public function resolveRouteBinding($value, $field = null) { return null; }
    public function resolveChildRouteBinding($childType, $value, $field) { return null; }
    public function localizedSlug($locale = null): string { return (string) $this->slug; }
    public function localized(string $field, ?string $locale = null): string
    {
        $field = ['excerpt' => 'description', 'content' => 'body'][$field] ?? $field;
        return ContentService::translated($this->translations ?? [], $field, $locale);
    }
    public function effectiveAccessPolicy(): ?string { return $this->access_policy; }
    public function embargoIsActive(): bool { return $this->embargo_until !== null && $this->embargo_until->isFuture(); }
}
