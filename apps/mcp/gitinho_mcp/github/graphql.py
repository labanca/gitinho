"""Named GraphQL queries.

Kept in one module so query drift is localized and reviewable. Each query
should be the minimum field set needed by its caller — keep the variable
naming consistent (`$org` for the configured organization).
"""

from __future__ import annotations

ORG_REPOS_PAGE = """
query OrgReposPage($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        nameWithOwner
        description
        isPrivate
        isArchived
        isFork
        isTemplate
        url
        primaryLanguage { name }
        diskUsage
        stargazerCount
        forkCount
        pushedAt
        updatedAt
        createdAt
        repositoryTopics(first: 20) { nodes { topic { name } } }
        defaultBranchRef { name }
        refs(refPrefix: "refs/heads/", first: 1) { totalCount }
        openIssues: issues(states: OPEN) { totalCount }
        openPRs: pullRequests(states: OPEN) { totalCount }
      }
    }
  }
}
"""
