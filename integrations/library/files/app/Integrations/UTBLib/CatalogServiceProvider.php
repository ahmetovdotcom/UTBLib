<?php

namespace App\Integrations\UTBLib;

use Illuminate\Support\ServiceProvider;

class CatalogServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        if (config('utblib_catalog.enabled', false)) {
            $this->app->bind(\App\Services\Library\CatalogReadService::class, CatalogReadService::class);
            $this->app->bind(\App\Services\Library\BookDetailReadService::class, BookDetailReadService::class);
        }
        if (config('utblib_catalog.content_enabled', false)) {
            $this->app->scoped(ContentService::class);
            $this->app->bind(\App\Services\ExternalResourceService::class, ExternalResourceService::class);
        }
    }

    public function boot(): void
    {
        if (config('utblib_catalog.enabled', false)) {
            $this->app->make(\Illuminate\Contracts\Http\Kernel::class)->prependMiddleware(RemoteCatalogBoundary::class);
        }
        if (config('utblib_catalog.content_enabled', false)) {
            $this->app->booted(function (): void {
                \Illuminate\Support\Facades\Route::middleware('web')->group(function (): void {
                    \Illuminate\Support\Facades\Route::get('/utblib-content/assets/{item}/{slot}', [ContentController::class, 'asset'])->whereNumber('item')->whereIn('slot', ['image', 'pdf']);
                    \Illuminate\Support\Facades\Route::post('/utblib-content/events/{item}/register', [ContentController::class, 'register'])->where('item', 'utblib-[0-9]+')->middleware('throttle:30,1');
                });
            });
        }
    }
}
