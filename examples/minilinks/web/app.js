/**
 * MiniLinks - Frontend Client Application
 * Standard-compliant Vanilla JavaScript communicating with /api/bookmarks
 */

(() => {
  'use strict';

  // Application State
  let bookmarksState = [];
  let currentSearchQuery = '';
  let isFavoritesFilterActive = false;
  let isArchivedFilterActive = false;
  let activeEditingId = null;
  let activeDeletingId = null;
  let searchDebounceTimer = null;
  let notificationTimer = null;
  let lastFocusedElement = null;

  // DOM Elements - Notification Banner
  const notificationBanner = document.getElementById('notification-banner');
  const notificationMessage = document.getElementById('notification-message');
  const notificationIcon = document.getElementById('notification-icon');
  const notificationCloseBtn = document.getElementById('notification-close');

  // DOM Elements - Header, Search & Filter Controls
  const searchInput = document.getElementById('search-input');
  const searchClearBtn = document.getElementById('search-clear-btn');
  const filterFavoritesBtn = document.getElementById('filter-favorites-btn');
  const filterArchivedBtn = document.getElementById('filter-archived-btn');
  const bookmarksCount = document.getElementById('bookmarks-count');
  const bookmarksList = document.getElementById('bookmarks-list');

  // DOM Elements - Create Bookmark Form
  const bookmarkForm = document.getElementById('bookmark-form');
  const bookmarkTitleInput = document.getElementById('bookmark-title');
  const bookmarkUrlInput = document.getElementById('bookmark-url');
  const bookmarkNotesInput = document.getElementById('bookmark-notes');
  const bookmarkTagsInput = document.getElementById('bookmark-tags');
  const bookmarkSubmitBtn = document.getElementById('bookmark-submit-btn');

  // DOM Elements - Edit Modal
  const editModal = document.getElementById('edit-modal');
  const editModalClose = document.getElementById('edit-modal-close');
  const editBookmarkForm = document.getElementById('edit-bookmark-form');
  const editBookmarkId = document.getElementById('edit-bookmark-id');
  const editTitleInput = document.getElementById('edit-title');
  const editUrlInput = document.getElementById('edit-url');
  const editNotesInput = document.getElementById('edit-notes');
  const editTagsInput = document.getElementById('edit-tags');
  const editCancelBtn = document.getElementById('edit-cancel-btn');
  const editSaveBtn = document.getElementById('edit-save-btn');

  // DOM Elements - Delete Modal
  const deleteModal = document.getElementById('delete-modal');
  const deleteModalClose = document.getElementById('delete-modal-close');
  const deleteBookmarkTitle = document.getElementById('delete-bookmark-title');
  const deleteCancelBtn = document.getElementById('delete-cancel-btn');
  const deleteConfirmBtn = document.getElementById('delete-confirm-btn');

  // Initialize
  document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    fetchBookmarks('', false, false);
  });

  /**
   * Normalize user-entered URL if missing scheme
   */
  function normalizeUrl(rawUrl) {
    const trimmed = (rawUrl || '').trim();
    if (!trimmed) return '';
    // If already has a scheme with :// (e.g. "https://...", "http://...", "ftp://..."), preserve it
    if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//i.test(trimmed)) {
      return trimmed;
    }
    // Otherwise default to https:// (handles "docs.python.org", "localhost:8000", "127.0.0.1:8080", etc.)
    return `https://${trimmed}`;
  }

  /**
   * Sanitize URL for safe use in href attribute (prevent javascript: XSS)
   */
  function safeHref(rawUrl) {
    if (!rawUrl) return '#';
    const trimmed = rawUrl.trim();
    if (/^(?:javascript|data|vbscript):/i.test(trimmed)) {
      return '#';
    }
    return normalizeUrl(trimmed);
  }

  /**
   * Safely read JSON response body with fallback
   */
  async function parseJsonResponse(response) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  /**
   * Initialize all UI event listeners
   */
  function initEventListeners() {
    // Search input with debounced querying
    searchInput.addEventListener('input', (e) => {
      const query = e.target.value;
      searchClearBtn.classList.toggle('hidden', !query);

      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => {
        currentSearchQuery = query.trim();
        fetchBookmarks(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
      }, 250);
    });

    // Immediate search on Enter key
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        clearTimeout(searchDebounceTimer);
        currentSearchQuery = searchInput.value.trim();
        fetchBookmarks(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
      }
    });

    // Handle native search clear button
    searchInput.addEventListener('search', () => {
      if (!searchInput.value) {
        searchClearBtn.classList.add('hidden');
        clearTimeout(searchDebounceTimer);
        currentSearchQuery = '';
        fetchBookmarks('', isFavoritesFilterActive, isArchivedFilterActive);
      }
    });

    // Clear search button click
    searchClearBtn.addEventListener('click', () => {
      searchInput.value = '';
      searchClearBtn.classList.add('hidden');
      currentSearchQuery = '';
      fetchBookmarks('', isFavoritesFilterActive, isArchivedFilterActive);
      searchInput.focus();
    });

    // Favorites filter button click
    if (filterFavoritesBtn) {
      filterFavoritesBtn.addEventListener('click', handleToggleFavoritesFilter);
    }

    // Archived filter button click
    if (filterArchivedBtn) {
      filterArchivedBtn.addEventListener('click', handleToggleArchivedFilter);
    }

    // Create bookmark form submission
    bookmarkForm.addEventListener('submit', handleCreateBookmark);

    // Edit bookmark form submission & modal controls
    editBookmarkForm.addEventListener('submit', handleSaveEdit);
    editCancelBtn.addEventListener('click', closeEditModal);
    editModalClose.addEventListener('click', closeEditModal);
    editModal.addEventListener('click', (e) => {
      if (e.target === editModal) closeEditModal();
    });

    // Delete bookmark confirmation & modal controls
    deleteConfirmBtn.addEventListener('click', handleConfirmDelete);
    deleteCancelBtn.addEventListener('click', closeDeleteModal);
    deleteModalClose.addEventListener('click', closeDeleteModal);
    deleteModal.addEventListener('click', (e) => {
      if (e.target === deleteModal) closeDeleteModal();
    });

    // Notification close button
    notificationCloseBtn.addEventListener('click', hideNotification);

    // Global keyboard shortcuts (Escape closes modals)
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (!editModal.classList.contains('hidden')) {
          closeEditModal();
        }
        if (!deleteModal.classList.contains('hidden')) {
          closeDeleteModal();
        }
      }
    });
  }

  /**
   * Toggle favorites filter state and reload bookmarks
   */
  function handleToggleFavoritesFilter() {
    isFavoritesFilterActive = !isFavoritesFilterActive;
    updateFavoritesFilterUI();
    fetchBookmarks(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
  }

  /**
   * Toggle archived filter state and reload bookmarks
   */
  function handleToggleArchivedFilter() {
    isArchivedFilterActive = !isArchivedFilterActive;
    updateArchivedFilterUI();
    fetchBookmarks(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
  }

  /**
   * Update favorites filter button visual indicator
   */
  function updateFavoritesFilterUI() {
    if (!filterFavoritesBtn) return;
    filterFavoritesBtn.classList.toggle('active', isFavoritesFilterActive);
    filterFavoritesBtn.setAttribute('aria-pressed', String(isFavoritesFilterActive));
    const starIcon = filterFavoritesBtn.querySelector('.filter-star-icon');
    if (starIcon) {
      starIcon.textContent = isFavoritesFilterActive ? '★' : '☆';
    }
  }

  /**
   * Update archived filter button visual indicator
   */
  function updateArchivedFilterUI() {
    if (!filterArchivedBtn) return;
    filterArchivedBtn.classList.toggle('active', isArchivedFilterActive);
    filterArchivedBtn.setAttribute('aria-pressed', String(isArchivedFilterActive));
  }

  /**
   * Fetch bookmarks from REST API with optional search query, favorites filter, and archived filter
   */
  async function fetchBookmarks(query = '', favoritesOnly = false, archivedOnly = false) {
    setLoadingState(true);
    try {
      const params = new URLSearchParams();
      if (query) {
        params.set('q', query);
      }
      if (favoritesOnly) {
        params.set('favorites', 'true');
      }
      if (archivedOnly) {
        params.set('archived', 'true');
      }

      const queryString = params.toString();
      const endpoint = queryString ? `/api/bookmarks?${queryString}` : '/api/bookmarks';

      const response = await fetch(endpoint, {
        headers: {
          'Accept': 'application/json',
        },
      });

      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error((data && data.error) || `Failed to load bookmarks (HTTP ${response.status})`);
      }

      bookmarksState = Array.isArray(data) ? data : [];
      renderBookmarks(bookmarksState, query, favoritesOnly, archivedOnly);
    } catch (err) {
      console.error('Error fetching bookmarks:', err);
      showNotification(err.message || 'Unable to load bookmarks', 'error');
      renderErrorState(err.message);
    } finally {
      setLoadingState(false);
    }
  }

  /**
   * Helper to parse comma-separated tags string into clean array
   */
  function parseTags(raw) {
    if (!raw) return [];
    return raw.split(',').map(t => t.trim()).filter(Boolean);
  }

  /**
   * Create a new bookmark
   */
  async function handleCreateBookmark(e) {
    e.preventDefault();

    const title = bookmarkTitleInput.value.trim();
    const rawUrl = bookmarkUrlInput.value.trim();
    const notes = bookmarkNotesInput.value.trim();
    const tags = parseTags(bookmarkTagsInput ? bookmarkTagsInput.value : '');

    if (!title) {
      showNotification('Title is required', 'error');
      bookmarkTitleInput.focus();
      return;
    }

    if (!rawUrl) {
      showNotification('URL is required', 'error');
      bookmarkUrlInput.focus();
      return;
    }

    const url = normalizeUrl(rawUrl);
    bookmarkSubmitBtn.disabled = true;

    try {
      const response = await fetch('/api/bookmarks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ title, url, notes, tags }),
      });

      const data = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error((data && data.error) || `Error creating bookmark (HTTP ${response.status})`);
      }

      // Reset form on success
      bookmarkForm.reset();
      showNotification('Bookmark added successfully', 'success');

      // Clear search query and reset favorites filter so the new bookmark is immediately visible
      if (currentSearchQuery) {
        searchInput.value = '';
        searchClearBtn.classList.add('hidden');
        currentSearchQuery = '';
      }
      if (isFavoritesFilterActive) {
        isFavoritesFilterActive = false;
        updateFavoritesFilterUI();
      }
      if (isArchivedFilterActive) {
        isArchivedFilterActive = false;
        updateArchivedFilterUI();
      }

      // Refresh listing
      await fetchBookmarks('', false, false);
    } catch (err) {
      console.error('Error creating bookmark:', err);
      showNotification(err.message || 'Failed to create bookmark', 'error');
    } finally {
      bookmarkSubmitBtn.disabled = false;
    }
  }

  /**
   * Open edit modal prefilled with bookmark data
   */
  function openEditModal(bookmark) {
    lastFocusedElement = document.activeElement;
    activeEditingId = bookmark.id;
    editBookmarkId.value = bookmark.id;
    editTitleInput.value = bookmark.title;
    editUrlInput.value = bookmark.url;
    editNotesInput.value = bookmark.notes || '';
    if (editTagsInput) {
      editTagsInput.value = Array.isArray(bookmark.tags) ? bookmark.tags.join(', ') : '';
    }

    editModal.classList.remove('hidden');
    editTitleInput.focus();
  }

  /**
   * Close edit modal and restore focus
   */
  function closeEditModal() {
    editModal.classList.add('hidden');
    activeEditingId = null;
    editBookmarkForm.reset();
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
      lastFocusedElement.focus();
    }
  }

  /**
   * Save edited bookmark via PATCH /api/bookmarks/:id
   */
  async function handleSaveEdit(e) {
    e.preventDefault();

    const id = activeEditingId;
    if (!id) return;

    const title = editTitleInput.value.trim();
    const rawUrl = editUrlInput.value.trim();
    const notes = editNotesInput.value.trim();
    const tags = parseTags(editTagsInput ? editTagsInput.value : '');

    if (!title) {
      showNotification('Title is required', 'error');
      editTitleInput.focus();
      return;
    }

    if (!rawUrl) {
      showNotification('URL is required', 'error');
      editUrlInput.focus();
      return;
    }

    const url = normalizeUrl(rawUrl);
    editSaveBtn.disabled = true;

    try {
      const response = await fetch(`/api/bookmarks/${id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ title, url, notes, tags }),
      });

      const updatedBookmark = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error((updatedBookmark && updatedBookmark.error) || `Failed to update bookmark (HTTP ${response.status})`);
      }

      showNotification('Bookmark updated successfully', 'success');
      closeEditModal();

      // Refresh list to keep timestamps & filtering consistent
      await fetchBookmarks(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
    } catch (err) {
      console.error('Error updating bookmark:', err);
      showNotification(err.message || 'Failed to update bookmark', 'error');
    } finally {
      editSaveBtn.disabled = false;
    }
  }

  /**
   * Open delete confirmation modal
   */
  function openDeleteModal(bookmark) {
    lastFocusedElement = document.activeElement;
    activeDeletingId = bookmark.id;
    deleteBookmarkTitle.textContent = bookmark.title;
    deleteModal.classList.remove('hidden');
    deleteConfirmBtn.focus();
  }

  /**
   * Close delete modal and restore focus
   */
  function closeDeleteModal() {
    deleteModal.classList.add('hidden');
    activeDeletingId = null;
    deleteBookmarkTitle.textContent = '';
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
      lastFocusedElement.focus();
    }
  }

  /**
   * Confirm deletion via DELETE /api/bookmarks/:id
   */
  async function handleConfirmDelete() {
    const id = activeDeletingId;
    if (!id) return;

    deleteConfirmBtn.disabled = true;

    try {
      const response = await fetch(`/api/bookmarks/${id}`, {
        method: 'DELETE',
        headers: {
          'Accept': 'application/json',
        },
      });

      const result = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error((result && result.error) || `Failed to delete bookmark (HTTP ${response.status})`);
      }

      closeDeleteModal();
      showNotification('Bookmark deleted successfully', 'success');

      // Immediately remove card element from DOM
      const cardEl = bookmarksList.querySelector(`[data-id="${id}"]`);
      if (cardEl) {
        cardEl.remove();
      }

      // Update in-memory state and count
      bookmarksState = bookmarksState.filter(bm => bm.id !== id);
      updateBookmarksCount(bookmarksState.length, currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);

      if (bookmarksState.length === 0) {
        renderEmptyState(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
      }
    } catch (err) {
      console.error('Error deleting bookmark:', err);
      showNotification(err.message || 'Failed to delete bookmark', 'error');
    } finally {
      deleteConfirmBtn.disabled = false;
    }
  }

  /**
   * Render bookmarks into container
   */
  function renderBookmarks(bookmarks, query = '', favoritesOnly = false, archivedOnly = false) {
    bookmarksList.innerHTML = '';
    updateBookmarksCount(bookmarks.length, query, favoritesOnly, archivedOnly);

    if (bookmarks.length === 0) {
      renderEmptyState(query, favoritesOnly, archivedOnly);
      return;
    }

    bookmarks.forEach(bookmark => {
      const card = createBookmarkCard(bookmark);
      bookmarksList.appendChild(card);
    });
  }

  /**
   * Construct DOM elements for a bookmark card safely without XSS risk
   */
  function createBookmarkCard(bookmark) {
    const isFav = Boolean(bookmark.is_favorite);
    const isArch = Boolean(bookmark.archived);

    const article = document.createElement('article');
    article.className = `bookmark-card${isFav ? ' is-favorite' : ''}${isArch ? ' is-archived' : ''}`;
    article.setAttribute('data-id', bookmark.id);

    // Card Header
    const cardHeader = document.createElement('div');
    cardHeader.className = 'card-header';

    const titleRow = document.createElement('div');
    titleRow.className = 'card-title-row';

    const titleH3 = document.createElement('h3');
    titleH3.className = 'card-title';

    const titleLink = document.createElement('a');
    titleLink.className = 'card-title-link';
    titleLink.href = safeHref(bookmark.url);
    titleLink.target = '_blank';
    titleLink.rel = 'noopener noreferrer';
    titleLink.textContent = bookmark.title;

    titleH3.appendChild(titleLink);

    if (isArch) {
      const badge = document.createElement('span');
      badge.className = 'badge badge-archived';
      badge.textContent = 'Archived';
      titleH3.appendChild(badge);
    }

    titleRow.appendChild(titleH3);

    // Favorite / Star toggle button (★ / ☆)
    const favBtn = document.createElement('button');
    favBtn.type = 'button';
    favBtn.id = `favorite-btn-${bookmark.id}`;
    favBtn.className = `favorite-toggle-btn${isFav ? ' is-favorite active' : ''}`;
    favBtn.setAttribute('data-id', bookmark.id);
    favBtn.setAttribute('aria-label', isFav ? 'Remove from favorites' : 'Mark as favorite');
    favBtn.setAttribute('aria-pressed', String(isFav));
    favBtn.title = isFav ? 'Remove from favorites' : 'Mark as favorite';
    favBtn.textContent = isFav ? '★' : '☆';

    favBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      handleToggleFavorite(bookmark.id, favBtn, article);
    });

    titleRow.appendChild(favBtn);
    cardHeader.appendChild(titleRow);

    // Visible URL Link with truncation
    const urlLink = document.createElement('a');
    urlLink.className = 'card-url-link';
    urlLink.href = safeHref(bookmark.url);
    urlLink.target = '_blank';
    urlLink.rel = 'noopener noreferrer';
    urlLink.title = bookmark.url;
    urlLink.textContent = bookmark.url;
    cardHeader.appendChild(urlLink);

    article.appendChild(cardHeader);

    // Notes block (if present)
    if (bookmark.notes && bookmark.notes.trim()) {
      const notesBlock = document.createElement('div');
      notesBlock.className = 'card-notes';
      notesBlock.textContent = bookmark.notes;
      article.appendChild(notesBlock);
    }

    // Tags block (if present)
    if (Array.isArray(bookmark.tags) && bookmark.tags.length > 0) {
      const tagsBlock = document.createElement('div');
      tagsBlock.className = 'card-tags';
      bookmark.tags.forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = tag;
        chip.title = `Filter by tag: ${tag}`;
        chip.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          searchInput.value = tag;
          searchClearBtn.classList.remove('hidden');
          currentSearchQuery = tag;
          fetchBookmarks(tag, isFavoritesFilterActive, isArchivedFilterActive);
        });
        tagsBlock.appendChild(chip);
      });
      article.appendChild(tagsBlock);
    }

    // Timestamps
    const metaBlock = document.createElement('div');
    metaBlock.className = 'card-meta';

    const createdSpan = document.createElement('span');
    createdSpan.textContent = `Created: ${formatTimestamp(bookmark.created_at)}`;
    metaBlock.appendChild(createdSpan);

    if (bookmark.updated_at && bookmark.updated_at !== bookmark.created_at) {
      const updatedSpan = document.createElement('span');
      updatedSpan.className = 'meta-updated';
      updatedSpan.textContent = `Updated: ${formatTimestamp(bookmark.updated_at)}`;
      metaBlock.appendChild(updatedSpan);
    }

    article.appendChild(metaBlock);

    // Card Footer with Actions
    const cardFooter = document.createElement('div');
    cardFooter.className = 'card-footer';

    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'btn btn-secondary btn-sm btn-edit';
    editBtn.innerHTML = `
      <svg class="btn-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
      </svg>
      Edit
    `;
    editBtn.addEventListener('click', () => {
      const currentBm = bookmarksState.find(b => b.id === bookmark.id) || bookmark;
      openEditModal(currentBm);
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'btn btn-danger btn-sm btn-delete';
    deleteBtn.innerHTML = `
      <svg class="btn-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
      </svg>
      Delete
    `;
    deleteBtn.addEventListener('click', () => {
      const currentBm = bookmarksState.find(b => b.id === bookmark.id) || bookmark;
      openDeleteModal(currentBm);
    });

    const isArchived = Boolean(bookmark.archived);
    const archiveBtn = document.createElement('button');
    archiveBtn.type = 'button';
    archiveBtn.className = `btn btn-secondary btn-sm btn-archive${isArchived ? ' is-archived' : ''}`;
    archiveBtn.innerHTML = `
      <span class="btn-archive-icon" aria-hidden="true">${isArchived ? '📤' : '📦'}</span>
      ${isArchived ? 'Restore' : 'Archive'}
    `;
    archiveBtn.title = isArchived ? 'Restore bookmark' : 'Archive bookmark';
    archiveBtn.addEventListener('click', () => {
      handleToggleArchive(bookmark.id, isArchived);
    });

    cardFooter.appendChild(editBtn);
    cardFooter.appendChild(archiveBtn);
    cardFooter.appendChild(deleteBtn);
    article.appendChild(cardFooter);

    return article;
  }

  /**
   * Toggle archive/restore status via POST /api/bookmarks/:id/archive or /restore
   */
  async function handleToggleArchive(id, isCurrentlyArchived) {
    const action = isCurrentlyArchived ? 'restore' : 'archive';
    try {
      const response = await fetch(`/api/bookmarks/${id}/${action}`, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
        },
      });

      const updated = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error((updated && updated.error) || `Failed to ${action} bookmark`);
      }

      showNotification(
        isCurrentlyArchived ? 'Bookmark restored from archive' : 'Bookmark moved to archive',
        'success',
        2000
      );

      await fetchBookmarks(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
    } catch (err) {
      console.error(`Error toggling archive status:`, err);
      showNotification(err.message || `Failed to ${action} bookmark`, 'error');
    }
  }

  /**
   * Toggle favorite/star status via PATCH /api/bookmarks/:id
   */
  async function handleToggleFavorite(id, favBtn, cardElement) {
    const currentBookmark = bookmarksState.find(b => b.id === id);
    const currentStatus = currentBookmark ? Boolean(currentBookmark.is_favorite) : favBtn.classList.contains('is-favorite');
    const nextStatus = !currentStatus;

    favBtn.disabled = true;

    try {
      const response = await fetch(`/api/bookmarks/${id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({ is_favorite: nextStatus }),
      });

      const updated = await parseJsonResponse(response);

      if (!response.ok) {
        throw new Error((updated && updated.error) || `Failed to update favorite status (HTTP ${response.status})`);
      }

      const newFavState = Boolean(updated.is_favorite);

      // Update in-memory state
      if (currentBookmark) {
        currentBookmark.is_favorite = newFavState;
        if (updated.updated_at) {
          currentBookmark.updated_at = updated.updated_at;
        }
      }

      // Update button visual state
      favBtn.classList.toggle('is-favorite', newFavState);
      favBtn.classList.toggle('active', newFavState);
      favBtn.setAttribute('aria-pressed', String(newFavState));
      favBtn.setAttribute('aria-label', newFavState ? 'Remove from favorites' : 'Mark as favorite');
      favBtn.title = newFavState ? 'Remove from favorites' : 'Mark as favorite';
      favBtn.textContent = newFavState ? '★' : '☆';

      // Update card container class and timestamp
      if (cardElement) {
        cardElement.classList.toggle('is-favorite', newFavState);

        if (updated.updated_at && updated.updated_at !== updated.created_at) {
          let updatedSpan = cardElement.querySelector('.meta-updated');
          if (updatedSpan) {
            updatedSpan.textContent = `Updated: ${formatTimestamp(updated.updated_at)}`;
          } else {
            const metaBlock = cardElement.querySelector('.card-meta');
            if (metaBlock) {
              updatedSpan = document.createElement('span');
              updatedSpan.className = 'meta-updated';
              updatedSpan.textContent = `Updated: ${formatTimestamp(updated.updated_at)}`;
              metaBlock.appendChild(updatedSpan);
            }
          }
        }
      }

      showNotification(
        newFavState ? 'Bookmark added to favorites' : 'Bookmark removed from favorites',
        'success',
        2000
      );

      // If favorites filter is currently active and item was unfavorited, remove card from view
      if (isFavoritesFilterActive && !newFavState) {
        if (cardElement) {
          cardElement.remove();
        }
        bookmarksState = bookmarksState.filter(b => b.id !== id);
        updateBookmarksCount(bookmarksState.length, currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);

        if (bookmarksState.length === 0) {
          renderEmptyState(currentSearchQuery, isFavoritesFilterActive, isArchivedFilterActive);
        }
      }
    } catch (err) {
      console.error('Error updating favorite status:', err);
      showNotification(err.message || 'Failed to update favorite status', 'error');
    } finally {
      favBtn.disabled = false;
    }
  }

  /**
   * Render empty state message
   */
  function renderEmptyState(query = '', favoritesOnly = false, archivedOnly = false) {
    bookmarksList.innerHTML = '';
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';

    if (archivedOnly) {
      if (query && favoritesOnly) {
        emptyState.innerHTML = `
          <div class="empty-state-icon" style="font-size: 2.5rem; line-height: 1;" aria-hidden="true">📦</div>
          <h3 class="empty-state-title">No archived favorite bookmarks found</h3>
          <p class="empty-state-text">No archived favorite bookmarks matched your search for "<strong>${escapeHtml(query)}</strong>".</p>
        `;
      } else if (query) {
        emptyState.innerHTML = `
          <div class="empty-state-icon" style="font-size: 2.5rem; line-height: 1;" aria-hidden="true">📦</div>
          <h3 class="empty-state-title">No archived bookmarks found</h3>
          <p class="empty-state-text">No archived bookmarks matched your search for "<strong>${escapeHtml(query)}</strong>". Try checking for spelling errors or searching for a different keyword.</p>
        `;
      } else if (favoritesOnly) {
        emptyState.innerHTML = `
          <div class="empty-state-icon" style="font-size: 2.5rem; line-height: 1;" aria-hidden="true">📦</div>
          <h3 class="empty-state-title">No archived favorite bookmarks yet</h3>
          <p class="empty-state-text">You have no archived bookmarks marked as favorites.</p>
        `;
      } else {
        emptyState.innerHTML = `
          <div class="empty-state-icon" style="font-size: 2.5rem; line-height: 1;" aria-hidden="true">📦</div>
          <h3 class="empty-state-title">No archived bookmarks</h3>
          <p class="empty-state-text">Bookmarks you archive will appear here. Archive bookmarks you don't need right now to keep your collection clean.</p>
        `;
      }
    } else if (query && favoritesOnly) {
      emptyState.innerHTML = `
        <svg class="empty-state-icon" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
        </svg>
        <h3 class="empty-state-title">No favorite bookmarks found</h3>
        <p class="empty-state-text">No favorite bookmarks matched your search for "<strong>${escapeHtml(query)}</strong>".</p>
      `;
    } else if (query) {
      emptyState.innerHTML = `
        <svg class="empty-state-icon" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <h3 class="empty-state-title">No bookmarks found</h3>
        <p class="empty-state-text">No bookmarks matched your search for "<strong>${escapeHtml(query)}</strong>". Try checking for spelling errors or searching for a different keyword.</p>
      `;
    } else if (favoritesOnly) {
      emptyState.innerHTML = `
        <svg class="empty-state-icon" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
        </svg>
        <h3 class="empty-state-title">No favorite bookmarks yet</h3>
        <p class="empty-state-text">Click the star icon (☆) on any bookmark card to add it to your favorites.</p>
      `;
    } else {
      emptyState.innerHTML = `
        <svg class="empty-state-icon" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
        </svg>
        <h3 class="empty-state-title">No bookmarks saved yet</h3>
        <p class="empty-state-text">Start building your collection by adding your first bookmark in the form above.</p>
      `;
    }

    bookmarksList.appendChild(emptyState);
  }

  /**
   * Render error state message
   */
  function renderErrorState(errorMessage) {
    bookmarksList.innerHTML = `
      <div class="empty-state">
        <h3 class="empty-state-title" style="color: var(--danger);">Failed to load bookmarks</h3>
        <p class="empty-state-text">${escapeHtml(errorMessage || 'Server error occurred')}</p>
      </div>
    `;
    bookmarksCount.textContent = 'Error';
  }

  /**
   * Update bookmarks count indicator
   */
  function updateBookmarksCount(count, query = '', favoritesOnly = false, archivedOnly = false) {
    if (archivedOnly) {
      if (query && favoritesOnly) {
        bookmarksCount.textContent = `${count} archived favorite ${count === 1 ? 'match' : 'matches'}`;
      } else if (query) {
        bookmarksCount.textContent = `${count} archived ${count === 1 ? 'match' : 'matches'}`;
      } else if (favoritesOnly) {
        bookmarksCount.textContent = `${count} archived ${count === 1 ? 'favorite' : 'favorites'}`;
      } else {
        bookmarksCount.textContent = `${count} ${count === 1 ? 'archived bookmark' : 'archived bookmarks'}`;
      }
    } else {
      if (query && favoritesOnly) {
        bookmarksCount.textContent = `${count} favorite ${count === 1 ? 'match' : 'matches'}`;
      } else if (query) {
        bookmarksCount.textContent = `${count} ${count === 1 ? 'match' : 'matches'}`;
      } else if (favoritesOnly) {
        bookmarksCount.textContent = `${count} ${count === 1 ? 'favorite' : 'favorites'}`;
      } else {
        bookmarksCount.textContent = `${count} ${count === 1 ? 'bookmark' : 'bookmarks'}`;
      }
    }
  }

  /**
   * Show status/notification feedback banner
   */
  function showNotification(message, type = 'info', duration = 3500) {
    clearTimeout(notificationTimer);

    notificationBanner.className = `notification-banner notification-${type}`;
    notificationMessage.textContent = message;

    if (type === 'success') {
      notificationIcon.innerHTML = `
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
          <polyline points="22 4 12 14.01 9 11.01"></polyline>
        </svg>
      `;
    } else if (type === 'error') {
      notificationIcon.innerHTML = `
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
      `;
    } else {
      notificationIcon.innerHTML = `
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
      `;
    }

    notificationBanner.classList.remove('hidden');

    if (duration > 0) {
      notificationTimer = setTimeout(hideNotification, duration);
    }
  }

  /**
   * Hide notification banner
   */
  function hideNotification() {
    clearTimeout(notificationTimer);
    notificationBanner.classList.add('hidden');
  }

  /**
   * Toggle loading visual state
   */
  function setLoadingState(isLoading) {
    bookmarksList.setAttribute('aria-busy', String(isLoading));
    if (isLoading && bookmarksState.length === 0) {
      bookmarksCount.textContent = 'Loading...';
    }
  }

  /**
   * Format ISO 8601 timestamp for display
   */
  function formatTimestamp(isoStr) {
    if (!isoStr) return '';
    try {
      const date = new Date(isoStr);
      if (isNaN(date.getTime())) return isoStr;

      return date.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr;
    }
  }

  /**
   * Escape HTML entities to prevent injection in innerHTML strings
   */
  function escapeHtml(str) {
    if (!str) return '';
    const span = document.createElement('span');
    span.textContent = String(str);
    return span.innerHTML;
  }
})();
