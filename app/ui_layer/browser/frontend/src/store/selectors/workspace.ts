import type { RootState } from '../index'

export const selectWorkspace = (state: RootState) => state.workspace
export const selectWorkspaceCurrentDirectory = (state: RootState) => state.workspace.currentDirectory
export const selectWorkspaceFiles = (state: RootState) => state.workspace.files
export const selectWorkspaceLoading = (state: RootState) => state.workspace.loading
export const selectWorkspaceLoadingMore = (state: RootState) => state.workspace.loadingMore
export const selectWorkspaceError = (state: RootState) => state.workspace.error
export const selectWorkspaceSelectedFile = (state: RootState) => state.workspace.selectedFile
export const selectWorkspaceFileContent = (state: RootState) => state.workspace.fileContent
export const selectWorkspaceFileIsBinary = (state: RootState) => state.workspace.fileIsBinary
export const selectWorkspaceTotal = (state: RootState) => state.workspace.total
export const selectWorkspaceHasMore = (state: RootState) => state.workspace.hasMore
export const selectWorkspaceOffset = (state: RootState) => state.workspace.offset
export const selectWorkspaceSearch = (state: RootState) => state.workspace.search
