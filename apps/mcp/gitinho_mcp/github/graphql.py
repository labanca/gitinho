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

ORG_OPEN_PRS = """
query OrgOpenPRs($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        pullRequests(states: OPEN) { totalCount }
      }
    }
  }
}
"""

ORG_OPEN_ISSUES = """
query OrgOpenIssues($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        issues(states: OPEN) { totalCount }
      }
    }
  }
}
"""

REPO_LAST_COMMIT = """
query RepoLastCommit($org: String!, $repo: String!) {
  repository(owner: $org, name: $repo) {
    defaultBranchRef {
      name
      target {
        ... on Commit {
          oid
          messageHeadline
          committedDate
          url
          author { name email user { login } }
        }
      }
    }
  }
}
"""

USER_LAST_ISSUE_IN_ORG = """
query UserLastIssue($q: String!) {
  search(query: $q, type: ISSUE, first: 1) {
    nodes {
      ... on Issue {
        title url createdAt repository { nameWithOwner } author { login }
      }
    }
  }
}
"""

USER_CONTRIBUTIONS = """
query UserContributions($login: String!, $from: DateTime!, $to: DateTime!, $org: ID) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to, organizationID: $org) {
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalRepositoryContributions
    }
  }
}
"""

ORG_MEMBERS = """
query OrgMembers($org: String!, $after: String) {
  organization(login: $org) {
    membersWithRole(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { login id name avatarUrl }
    }
  }
}
"""

ORG_ID = """
query OrgId($org: String!) {
  organization(login: $org) { id }
}
"""

ORG_REPOS_WITH_DATAPACKAGE = """
query OrgReposWithDatapackage($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after, orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        nameWithOwner
        description
        isPrivate
        isArchived
        url
        pushedAt
        defaultBranchRef { name }
        repositoryTopics(first: 20) { nodes { topic { name } } }
        datapackage: object(expression: "HEAD:datapackage.json") {
          ... on Blob { byteSize }
        }
      }
    }
  }
}
"""

ORG_DISCUSSIONS = """
query OrgDiscussions($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        discussions(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
          totalCount
          nodes { title url createdAt author { login } }
        }
      }
    }
  }
}
"""
