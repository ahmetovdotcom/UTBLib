<?php

namespace App\Integrations\UTBLib;

/** Adapter only: the original Blade templates and public controllers remain unchanged. */
class CatalogReadService extends \App\Services\Library\CatalogReadService
{
    public function search(
        string $query = '',
        ?string $title = null,
        ?string $author = null,
        ?string $publisher = null,
        ?string $isbn = null,
        ?string $subject = null,
        ?string $udc = null,
        ?string $language = null,
        int $page = 1,
        int $limit = 10,
        string $sort = 'popular',
        ?int $yearFrom = null,
        ?int $yearTo = null,
        bool $availableOnly = false,
        bool $physicalOnly = false,
        ?string $materialType = null,
        ?string $subjectId = null,
        ?string $institution = null,
        bool $includeTotal = true,
        bool $includeLocations = true,
        ?string $resourceType = null,
        ?string $fund = null,
        ?string $branch = null,
        ?string $category = null,
        ?string $availability = null,
        ?string $format = null,
        bool $completeOnly = false,
        bool $includeUdcCode = false,
        array $academicFilters = [],
        bool $facultyWorksOnly = false,
    ): array {
        if ($academicFilters !== [] || $facultyWorksOnly) {
            return ['data' => [], 'meta' => ['page' => $page, 'per_page' => $limit, 'total' => 0, 'totalPages' => 1, 'total_pages' => 1]];
        }
        return app(CatalogClient::class)->get('catalog', [
            'q' => $query, 'title' => $title, 'author' => $author, 'publisher' => $publisher,
            'isbn' => $isbn, 'subject' => $subject, 'subject_id' => $subjectId, 'udc' => $udc,
            'language' => $language, 'page' => $page, 'limit' => $limit, 'sort' => $sort,
            'year_from' => $yearFrom, 'year_to' => $yearTo, 'available_only' => $availableOnly ? 'true' : 'false',
            'physical_only' => $physicalOnly ? 'true' : 'false', 'material_type' => $materialType,
            'institution' => $institution, 'resource_type' => $resourceType, 'fund' => $fund,
            'branch' => $branch, 'category' => $category, 'availability' => $availability, 'format' => $format,
        ]);
    }

    public function facets(): array
    {
        return app(CatalogClient::class)->get('facets');
    }

    public function yearBounds(): array
    {
        return $this->facets()['years'];
    }

    public function popularByInstitution(string $institution, int $limit = 4): array
    {
        return array_map(static fn (array $book): array => [
            'id' => $book['id'], 'isbn' => $book['isbn']['raw'], 'title' => $book['title']['display'],
            'author' => $book['primaryAuthor'], 'copies' => $book['copies']['available'],
            'totalCopies' => $book['copies']['total'], 'issueCount' => $book['indicators']['issueCount'],
            'coverPath' => $book['coverPath'],
        ], $this->search(institution: $institution, limit: $limit)['data']);
    }

    public function institutionCopiesCount(string $institution): int
    {
        return (int) $this->search(institution: $institution, limit: 1)['meta']['total_copies'];
    }
}
