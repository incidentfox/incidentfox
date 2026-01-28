'use client';

import React, { useCallback, useEffect, useState, useMemo, useRef } from 'react';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  addEdge,
  useReactFlow,
  ReactFlowProvider,
  Node,
  Edge,
  MarkerType,
  Handle,
  Position,
  NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Search,
  MessageSquare,
  ChevronDown,
  ChevronRight,
  Loader2,
  Info,
  Layers,
  GitBranch,
  X,
  Send,
  ExternalLink,
  Sparkles,
} from 'lucide-react';
import { apiFetch } from '@/lib/apiClient';
import { HelpTip } from '@/components/onboarding/HelpTip';

// Types matching API responses
interface GraphNodeData {
  id: string;
  label: string;
  layer: number;
  text_preview: string;
  has_children: boolean;
  children_count: number;
  source_url?: string;
  is_root?: boolean;
}

interface GraphEdgeData {
  source: string;
  target: string;
}

interface TreeStats {
  tree: string;
  total_nodes: number;
  layers: number;
  leaf_nodes: number;
  summary_nodes: number;
  layer_counts: Record<number, number>;
}

interface SearchResult {
  id: string;
  label: string;
  layer: number;
  text_preview: string;
  score: number;
  source_url?: string;
}

interface Citation {
  index: number;
  source: string;
  rel_path?: string;
  node_ids: number[];
}

interface AnswerResponse {
  question: string;
  answer: string;
  tree: string;
  context_chunks: string[];
  citations: Citation[];
}

// Color palette for layers
const layerColors = [
  { bg: '#fef3c7', border: '#f59e0b', text: '#92400e' }, // Layer 0 - amber (leaves)
  { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' }, // Layer 1 - blue
  { bg: '#dcfce7', border: '#22c55e', text: '#166534' }, // Layer 2 - green
  { bg: '#f3e8ff', border: '#a855f7', text: '#7e22ce' }, // Layer 3 - purple
  { bg: '#fce7f3', border: '#ec4899', text: '#9d174d' }, // Layer 4 - pink
  { bg: '#e0f2fe', border: '#0ea5e9', text: '#0369a1' }, // Layer 5 - sky
  { bg: '#111827', border: '#f97316', text: '#f97316' }, // Root - dark with orange
];

// Custom node component
function TreeNode({ data, selected }: NodeProps) {
  const nodeData = data as unknown as GraphNodeData & {
    onExpand?: (id: string) => void;
    onSelect?: (id: string) => void;
    isExpanded?: boolean;
    isLoading?: boolean;
    isHighlighted?: boolean;
  };

  const layer = nodeData.layer || 0;
  const colorIdx = Math.min(layer, layerColors.length - 1);
  const colors = nodeData.is_root ? layerColors[layerColors.length - 1] : layerColors[colorIdx];

  // Root node is smaller
  const sizeClasses = nodeData.is_root
    ? 'min-w-[140px] max-w-[160px] py-2'
    : 'min-w-[200px] max-w-[300px]';

  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 ${sizeClasses} cursor-pointer
        transition-all duration-200 hover:shadow-lg
        ${selected ? 'ring-2 ring-orange-500 ring-offset-2' : ''}
        ${nodeData.isHighlighted ? 'ring-2 ring-yellow-400 animate-pulse' : ''}
      `}
      style={{
        backgroundColor: colors.bg,
        borderColor: colors.border,
        color: colors.text,
      }}
      onClick={() => nodeData.onSelect?.(nodeData.id)}
    >
      {/* Top handle for incoming edges */}
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span 
              className="text-xs font-bold px-1.5 py-0.5 rounded"
              style={{ backgroundColor: colors.border, color: 'white' }}
            >
              L{layer}
            </span>
            {nodeData.is_root && (
              <span className="text-xs font-bold">ROOT</span>
            )}
          </div>
          <p className="text-sm font-medium line-clamp-2 leading-tight">
            {nodeData.text_preview?.slice(0, 80) || nodeData.label}
            {(nodeData.text_preview?.length || 0) > 80 && '...'}
          </p>
        </div>
        
        {nodeData.has_children && (
          <button
            className="flex-shrink-0 p-1 hover:bg-white/50 rounded transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              nodeData.onExpand?.(nodeData.id);
            }}
          >
            {nodeData.isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : nodeData.isExpanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
        )}
      </div>
      
      {nodeData.children_count > 0 && (
        <div className="text-xs mt-1 opacity-70">
          {nodeData.children_count} children
        </div>
      )}
      
      {/* Bottom handle for outgoing edges */}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </div>
  );
}

const nodeTypes = {
  treeNode: TreeNode,
};

interface TreeExplorerProps {
  treeName?: string;
}

export function TreeExplorer({ treeName = 'mega_ultra_v2' }: TreeExplorerProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [stats, setStats] = useState<TreeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // First-time load state (tree not cached, needs S3 download)
  const [isFirstTimeLoad, setIsFirstTimeLoad] = useState(false);
  const [loadingProgress, setLoadingProgress] = useState<string>('');
  
  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  
  // Q&A state
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AnswerResponse | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [showQA, setShowQA] = useState(false);
  
  // Selected node state
  const [selectedNode, setSelectedNode] = useState<GraphNodeData | null>(null);
  const [selectedNodeText, setSelectedNodeText] = useState<string | null>(null);
  const [loadingNodeText, setLoadingNodeText] = useState(false);
  const [showDetailsPanel, setShowDetailsPanel] = useState(false);
  
  // Track expanded and loading nodes
  const expandedNodes = useRef<Set<string>>(new Set());
  const loadingNodes = useRef<Set<string>>(new Set());
  
  // Refs for stable handler references
  const handleExpandRef = useRef<(id: string) => void>(() => {});
  const handleNodeSelectRef = useRef<(id: string) => void>(() => {});

  // React Flow instance ref for programmatic control (pan, zoom)
  const reactFlowInstance = useRef<any>(null);

  // Load tree stats
  useEffect(() => {
    async function loadStats() {
      try {
        const res = await apiFetch(`/api/team/knowledge/tree/stats?tree=${treeName}`);
        if (res.ok) {
          const data = await res.json();
          setStats(data);
        }
      } catch (e) {
        console.error('Failed to load stats:', e);
      }
    }
    loadStats();
  }, [treeName]);

  // Load initial tree structure - start collapsed with only ROOT node visible
  useEffect(() => {
    async function loadTree() {
      setLoading(true);
      setError(null);
      setIsFirstTimeLoad(false);
      setLoadingProgress('');

      try {
        // Pre-flight check: see if tree is already cached
        // This helps us show appropriate loading messages
        let needsDownload = false;
        try {
          const cacheRes = await apiFetch('/api/team/knowledge/tree/cache');
          if (cacheRes.ok) {
            const cacheData = await cacheRes.json();
            const cachedTrees = cacheData.trees?.map((t: { name: string }) => t.name) || [];
            const isCached = cachedTrees.includes(treeName);

            if (!isCached) {
              needsDownload = true;
              setIsFirstTimeLoad(true);
              setLoadingProgress('Downloading knowledge base from cloud storage...');
            }
          }
        } catch (e) {
          // If cache check fails, proceed anyway - non-critical
          console.debug('Cache check failed, proceeding:', e);
        }

        // Load tree stats - this triggers lazy loading if tree is not cached
        // Use AbortController with extended timeout for first-time loads
        const controller = new AbortController();
        const timeoutMs = needsDownload ? 300000 : 60000; // 5 min for first load, 1 min otherwise
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

        const statsRes = await apiFetch(`/api/team/knowledge/tree/stats?tree=${treeName}`, {
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!statsRes.ok) {
          const err = await statsRes.json();
          throw new Error(err.error || 'Failed to load tree');
        }

        const statsData = await statsRes.json();
        setLoadingProgress('Building tree visualization...');
        
        // Create just the ROOT node initially
        // Use refs for handlers to avoid dependency issues
        const rootNode: Node = {
          id: '__root__',
          type: 'treeNode',
          position: { x: 0, y: 0 },
          data: {
            id: '__root__',
            label: 'ROOT',
            layer: (statsData.layers || 5) + 1, // Root is above the highest layer
            text_preview: 'Knowledge Base Root',
            has_children: true,
            children_count: statsData.layer_counts?.[statsData.layers] || statsData.total_nodes || 0,
            source_url: null,
            is_root: true,
            onExpand: (id: string) => handleExpandRef.current(id),
            onSelect: (id: string) => handleNodeSelectRef.current(id),
            isExpanded: false,
            isLoading: false,
            isHighlighted: false,
          } as Record<string, unknown>,
        };
        
        setNodes([rootNode]);
        setEdges([]);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    
    loadTree();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [treeName, setNodes, setEdges]);

  // Layout nodes in a hierarchical structure
  function layoutNodes(apiNodes: GraphNodeData[]): Node[] {
    // Group by layer
    const byLayer: Record<number, GraphNodeData[]> = {};
    for (const n of apiNodes) {
      const layer = n.layer;
      if (!byLayer[layer]) byLayer[layer] = [];
      byLayer[layer].push(n);
    }
    
    const layers = Object.keys(byLayer).map(Number).sort((a, b) => b - a); // Top to bottom
    const flowNodes: Node[] = [];
    
    const nodeWidth = 280;
    const nodeHeight = 100;
    const horizontalGap = 40;
    const verticalGap = 120;
    
    for (let layerIdx = 0; layerIdx < layers.length; layerIdx++) {
      const layer = layers[layerIdx];
      const layerNodes = byLayer[layer];
      const y = layerIdx * (nodeHeight + verticalGap);
      const totalWidth = layerNodes.length * (nodeWidth + horizontalGap) - horizontalGap;
      const startX = -totalWidth / 2;
      
      for (let i = 0; i < layerNodes.length; i++) {
        const n = layerNodes[i];
        flowNodes.push({
          id: n.id,
          type: 'treeNode',
          position: { x: startX + i * (nodeWidth + horizontalGap), y },
          data: {
            ...n,
            onExpand: handleExpand,
            onSelect: handleNodeSelect,
            isExpanded: expandedNodes.current.has(n.id),
            isLoading: loadingNodes.current.has(n.id),
            isHighlighted: highlightedNodes.has(n.id),
          },
        });
      }
    }
    
    return flowNodes;
  }

  // Helper to find all descendant node IDs
  const findDescendants = useCallback((parentId: string, currentEdges: Edge[]): Set<string> => {
    const descendants = new Set<string>();
    const queue = [parentId];
    
    while (queue.length > 0) {
      const current = queue.shift()!;
      // Find all edges where this node is the source
      const childEdges = currentEdges.filter(e => e.source === current);
      for (const edge of childEdges) {
        if (!descendants.has(edge.target)) {
          descendants.add(edge.target);
          queue.push(edge.target);
        }
      }
    }
    
    return descendants;
  }, []);

  // Handle node expansion (lazy load children)
  const handleExpand = useCallback(async (nodeId: string) => {
    if (loadingNodes.current.has(nodeId)) return;
    
    if (expandedNodes.current.has(nodeId)) {
      // Collapse: remove all descendants
      expandedNodes.current.delete(nodeId);
      
      // Find all descendants to remove
      const descendantsToRemove = findDescendants(nodeId, edges);
      
      // Also mark any expanded descendants as collapsed
      descendantsToRemove.forEach(id => expandedNodes.current.delete(id));
      
      // Remove descendant nodes and their edges
      setNodes((nds) => nds
        .filter(n => !descendantsToRemove.has(n.id))
        .map(n => n.id === nodeId 
          ? { ...n, data: { ...n.data, isExpanded: false } }
          : n
        )
      );
      setEdges((eds) => eds.filter(e => 
        !descendantsToRemove.has(e.target) && e.source !== nodeId
      ));
      return;
    }
    
    loadingNodes.current.add(nodeId);
    setNodes((nds) => nds.map(n => 
      n.id === nodeId 
        ? { ...n, data: { ...n.data, isLoading: true } }
        : n
    ));
    
    try {
      let children: GraphNodeData[] = [];
      let newEdges: GraphEdgeData[] = [];
      
      if (nodeId === '__root__') {
        // Special case: expanding root node - fetch top layer from tree structure
        const res = await apiFetch(`/api/team/knowledge/tree?tree=${treeName}&maxLayers=1&maxNodesPerLayer=30`);
        if (!res.ok) throw new Error('Failed to load top layer');
        
        const data = await res.json();
        // Filter out the root node itself from the response
        children = (data.nodes || []).filter((n: GraphNodeData) => n.id !== '__root__');
        // Create edges from root to each top-layer node
        newEdges = children.map((child: GraphNodeData) => ({
          source: '__root__',
          target: child.id,
        }));
      } else {
        // Normal case: fetch children from node children endpoint
        const res = await apiFetch(`/api/team/knowledge/tree/nodes/${nodeId}/children?tree=${treeName}`);
        if (!res.ok) throw new Error('Failed to load children');
        
        const data = await res.json();
        children = data.children || [];
        newEdges = data.edges || [];
      }
      
      if (children.length > 0) {
        // Get current parent node position
        const parentNode = nodes.find(n => n.id === nodeId);
        if (!parentNode) return;
        
        // Calculate layout for children
        const nodeWidth = 280;
        const horizontalGap = 40;
        const totalWidth = children.length * (nodeWidth + horizontalGap) - horizontalGap;
        const startX = parentNode.position.x - totalWidth / 2 + nodeWidth / 2;
        
        // Add new nodes below parent
        const newNodes: Node[] = children.map((child: GraphNodeData, i: number) => ({
          id: child.id,
          type: 'treeNode',
          position: {
            x: startX + i * (nodeWidth + horizontalGap),
            y: parentNode.position.y + 150,
          },
          data: {
            ...child,
            onExpand: (id: string) => handleExpandRef.current(id),
            onSelect: (id: string) => handleNodeSelectRef.current(id),
            isHighlighted: highlightedNodes.has(child.id),
          },
        }));
        
        const newFlowEdges: Edge[] = newEdges.map((e: GraphEdgeData) => ({
          id: `${e.source}-${e.target}`,
          source: e.source,
          target: e.target,
          type: 'smoothstep',
          animated: false,
          style: { stroke: '#94a3b8', strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8' },
        }));
        
        setNodes((nds) => [...nds.filter(n => !children.some((c: GraphNodeData) => c.id === n.id)), ...newNodes]);
        setEdges((eds) => [...eds.filter(e => !newFlowEdges.some(ne => ne.id === e.id)), ...newFlowEdges]);
        
        expandedNodes.current.add(nodeId);
      }
    } catch (e) {
      console.error('Failed to expand node:', e);
    } finally {
      loadingNodes.current.delete(nodeId);
      setNodes((nds) => nds.map(n => 
        n.id === nodeId 
          ? { ...n, data: { ...n.data, isLoading: false, isExpanded: expandedNodes.current.has(nodeId) } }
          : n
      ));
    }
  }, [nodes, edges, treeName, setNodes, setEdges, highlightedNodes, findDescendants]);

  // Update refs with latest handlers
  handleExpandRef.current = handleExpand;

  // Handle node selection
  const handleNodeSelect = useCallback(async (nodeId: string) => {
    if (nodeId === '__root__') return;
    
    const node = nodes.find(n => n.id === nodeId);
    if (!node) return;
    
    const nodeData = node.data as unknown as GraphNodeData;
    setSelectedNode(nodeData);
    setShowDetailsPanel(true); // Show the panel when a node is selected
    setLoadingNodeText(true);
    setSelectedNodeText(null);
    
    try {
      const res = await apiFetch(`/api/team/knowledge/tree/nodes/${nodeId}?tree=${treeName}`);
      if (res.ok) {
        const data = await res.json();
        // The API returns the full node data with text_preview field
        setSelectedNodeText(data.text_preview || data.text || nodeData.text_preview);
      } else {
        // Fallback to preview text from the node data
        setSelectedNodeText(nodeData.text_preview);
      }
    } catch (e) {
      console.error('Failed to load node text:', e);
      // Fallback to preview text
      setSelectedNodeText(nodeData.text_preview);
    } finally {
      setLoadingNodeText(false);
    }
  }, [nodes, treeName]);

  // Update refs with latest handlers
  handleNodeSelectRef.current = handleNodeSelect;

  // Handle selecting a search result - works even if node isn't visible in tree
  const handleSelectSearchResult = useCallback(async (result: SearchResult) => {
    // Create a GraphNodeData from the search result
    const nodeData: GraphNodeData = {
      id: result.id,
      label: result.label,
      layer: result.layer,
      text_preview: result.text_preview,
      has_children: false,
      children_count: 0,
      source_url: result.source_url,
    };

    setSelectedNode(nodeData);
    setShowDetailsPanel(true);
    setLoadingNodeText(true);
    setSelectedNodeText(null);

    // Check if node exists in the tree and pan to it
    const existingNode = nodes.find(n => n.id === result.id);
    if (existingNode && reactFlowInstance.current) {
      // Pan to the node with animation
      reactFlowInstance.current.setCenter(
        existingNode.position.x + 140, // Center on node (half width)
        existingNode.position.y + 50,  // Center on node (half height)
        { zoom: 1, duration: 500 }
      );
    }

    // Fetch full node text
    try {
      const res = await apiFetch(`/api/team/knowledge/tree/nodes/${result.id}?tree=${treeName}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedNodeText(data.text || data.text_preview || result.text_preview);
        // Update source_url if returned
        if (data.source_url) {
          setSelectedNode(prev => prev ? { ...prev, source_url: data.source_url } : prev);
        }
      } else {
        setSelectedNodeText(result.text_preview);
      }
    } catch (e) {
      console.error('Failed to load node text:', e);
      setSelectedNodeText(result.text_preview);
    } finally {
      setLoadingNodeText(false);
    }
  }, [nodes, treeName]);

  // Handle search
  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    
    setIsSearching(true);
    setSearchResults([]);
    
    try {
      const res = await apiFetch('/api/team/knowledge/tree/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery, tree: treeName, limit: 20 }),
      });
      
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.results || []);
        
        // Highlight matching nodes
        const matchIds = new Set<string>(data.results.map((r: SearchResult) => r.id));
        setHighlightedNodes(matchIds);
        
        // Update node highlighting
        setNodes((nds) => nds.map(n => ({
          ...n,
          data: { ...n.data, isHighlighted: matchIds.has(n.id) },
        })));
      }
    } catch (e) {
      console.error('Search failed:', e);
    } finally {
      setIsSearching(false);
    }
  }, [searchQuery, treeName, setNodes]);

  // Handle Q&A
  const handleAsk = useCallback(async () => {
    if (!question.trim()) return;
    
    setIsAsking(true);
    setAnswer(null);
    
    try {
      const res = await apiFetch('/api/team/knowledge/tree/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, tree: treeName, top_k: 5 }),
      });
      
      if (res.ok) {
        const data = await res.json();
        setAnswer(data);
      }
    } catch (e) {
      console.error('Ask failed:', e);
    } finally {
      setIsAsking(false);
    }
  }, [question, treeName]);

  // Clear highlights
  const clearHighlights = useCallback(() => {
    setHighlightedNodes(new Set());
    setSearchResults([]);
    setNodes((nds) => nds.map(n => ({
      ...n,
      data: { ...n.data, isHighlighted: false },
    })));
  }, [setNodes]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center max-w-md">
          <Loader2 className="w-8 h-8 animate-spin text-orange-500 mx-auto mb-3" />
          {isFirstTimeLoad ? (
            <>
              <p className="text-gray-700 dark:text-gray-200 font-medium mb-2">
                First-time setup for this knowledge base
              </p>
              <p className="text-gray-500 text-sm mb-2">
                {loadingProgress || 'Preparing knowledge base...'}
              </p>
              <p className="text-gray-400 text-xs">
                This may take 1-2 minutes. Subsequent loads will be instant.
              </p>
            </>
          ) : (
            <p className="text-gray-500">Loading knowledge tree...</p>
          )}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center max-w-md">
          <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-3">
            <X className="w-6 h-6 text-red-500" />
          </div>
          <p className="text-red-500 font-medium mb-2">Failed to load tree</p>
          <p className="text-gray-500 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex">
      {/* Main graph area */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          onInit={(instance) => { reactFlowInstance.current = instance; }}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.1}
          maxZoom={2}
          defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e2e8f0" />
          <Controls className="!bg-gray-50/90 dark:!bg-gray-800/90 !backdrop-blur-sm !shadow-md !border !border-gray-200 dark:!border-gray-700 [&_button]:!bg-gray-700 [&_button]:!text-white [&_button]:!border-gray-600 [&_button:hover]:!bg-gray-600" />
          <MiniMap
            nodeColor={(node) => {
              const layer = (node.data as unknown as GraphNodeData).layer || 0;
              return layerColors[Math.min(layer, layerColors.length - 2)].border;
            }}
            className="!bg-gray-50/90 dark:!bg-gray-800/90 !backdrop-blur-sm !border !border-gray-200 dark:!border-gray-700"
          />
        </ReactFlow>
        
        {/* Stats overlay */}
        {stats && (
          <div className="absolute top-4 left-4 bg-white dark:bg-gray-900 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 p-4 text-sm">
            <div className="flex items-center gap-2 mb-2">
              <Layers className="w-4 h-4 text-orange-500" />
              <span className="font-semibold text-gray-900 dark:text-white">{stats.tree}</span>
              <HelpTip id="tree-stats" position="right">
                <strong>RAPTOR Tree</strong> organizes your knowledge hierarchically. <em>Leaf nodes</em> (Layer 0) contain original content. Higher layers contain AI-generated <em>summaries</em> that group related information. Click nodes to expand and explore.
              </HelpTip>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-gray-600 dark:text-gray-400">
              <span>Total Nodes:</span>
              <span className="font-medium text-gray-900 dark:text-white">{stats.total_nodes.toLocaleString()}</span>
              <span>Layers:</span>
              <span className="font-medium text-gray-900 dark:text-white">{stats.layers}</span>
              <span>Leaf Nodes:</span>
              <span className="font-medium text-gray-900 dark:text-white">{stats.leaf_nodes.toLocaleString()}</span>
              <span>Summaries:</span>
              <span className="font-medium text-gray-900 dark:text-white">{stats.summary_nodes.toLocaleString()}</span>
            </div>
          </div>
        )}
        
        {/* Search bar */}
        <div className="absolute top-4 right-4 w-80">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="flex items-center p-3 border-b border-gray-100 dark:border-gray-800">
              <Search className="w-4 h-4 text-gray-400 mr-2" />
              <HelpTip id="tree-search" position="left">
                <strong>Semantic search</strong> finds relevant content across all layers. Results are ranked by similarity score. Click a result to view details, or expand nodes in the tree to see the full context.
              </HelpTip>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="Search knowledge..."
                className="flex-1 text-sm bg-transparent outline-none text-gray-900 dark:text-white placeholder-gray-400"
              />
              {isSearching ? (
                <Loader2 className="w-4 h-4 animate-spin text-orange-500" />
              ) : (
                <button
                  onClick={handleSearch}
                  className="text-orange-500 hover:text-orange-600 text-sm font-medium"
                >
                  Search
                </button>
              )}
            </div>
            
            {searchResults.length > 0 && (
              <div className="max-h-64 overflow-y-auto">
                <div className="p-2 flex items-center justify-between bg-gray-50 dark:bg-gray-800">
                  <span className="text-xs text-gray-500">{searchResults.length} results</span>
                  <button onClick={clearHighlights} className="text-xs text-gray-500 hover:text-gray-700">
                    Clear
                  </button>
                </div>
                {searchResults.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => handleSelectSearchResult(r)}
                    className="w-full p-3 text-left hover:bg-gray-50 dark:hover:bg-gray-800 border-b border-gray-100 dark:border-gray-800 last:border-0"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className="text-xs font-bold px-1.5 py-0.5 rounded text-white"
                        style={{ backgroundColor: layerColors[Math.min(r.layer, layerColors.length - 2)].border }}
                      >
                        L{r.layer}
                      </span>
                      <span className="text-xs text-gray-400">Score: {(r.score * 100).toFixed(0)}%</span>
                      {r.source_url && (
                        <ExternalLink className="w-3 h-3 text-gray-400" />
                      )}
                    </div>
                    <p className="text-sm text-gray-700 dark:text-gray-300 line-clamp-2">
                      {r.text_preview}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
          
          {/* Q&A toggle */}
          <div className="mt-3 flex items-center gap-2">
            <button
              onClick={() => setShowQA(!showQA)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl font-medium transition-all ${
                showQA
                  ? 'bg-orange-500 text-white shadow-lg'
                  : 'bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
              }`}
            >
              <MessageSquare className="w-4 h-4" />
              Ask the Knowledge Base
            </button>
            <HelpTip id="tree-qa" position="left">
              <strong>Q&A</strong> lets you ask natural language questions. The AI retrieves relevant context from your knowledge base and generates an answer with citations to the source documents.
            </HelpTip>
          </div>
        </div>
      </div>
      
      {/* Side panels - only show when there's content to display */}
      {(showQA || showDetailsPanel) && (
        <div className="w-96 border-l border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex flex-col">
          {/* Q&A Panel */}
          {showQA && (
            <div className="border-b border-gray-200 dark:border-gray-800 p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-orange-500" />
                  <h3 className="font-semibold text-gray-900 dark:text-white">Ask a Question</h3>
                </div>
                <button
                  onClick={() => setShowQA(false)}
                  className="text-gray-400 hover:text-gray-600 p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              
              <div className="flex gap-2 mb-3">
                <input
                  type="text"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
                  placeholder="e.g., How do I debug OOMKilled pods?"
                  className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white"
                />
                <button
                  onClick={handleAsk}
                  disabled={isAsking || !question.trim()}
                  className="px-3 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isAsking ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
              </div>
              
              {answer && (
                <div className="bg-gradient-to-r from-orange-50 to-amber-50 dark:from-orange-900/20 dark:to-amber-900/20 rounded-lg p-4 border border-orange-200 dark:border-orange-800">
                  <p className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap">
                    {answer.answer}
                  </p>
                  {answer.citations.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-orange-200 dark:border-orange-800">
                      <p className="text-xs font-medium text-gray-500 mb-2">Sources:</p>
                      <div className="space-y-1">
                        {answer.citations.map((c) => (
                          <div key={c.index} className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                            <span className="font-bold">[{c.index}]</span>
                            {c.source ? (
                              <a
                                href={c.source}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="truncate hover:text-blue-500 hover:underline"
                                title={c.source}
                              >
                                {c.rel_path || c.source}
                              </a>
                            ) : (
                              <span className="truncate">{c.rel_path}</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          
          {/* Selected node panel - only show when a node is selected and panel is open */}
          {showDetailsPanel && selectedNode && (
            <div className="flex-1 overflow-y-auto">
              <div className="p-4">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <GitBranch className="w-5 h-5 text-gray-400" />
                    <h3 className="font-semibold text-gray-900 dark:text-white">Node Details</h3>
                  </div>
                  <button
                    onClick={() => {
                      setSelectedNode(null);
                      setShowDetailsPanel(false);
                      setSelectedNodeText(null);
                    }}
                    className="text-gray-400 hover:text-gray-600 p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span 
                      className="text-xs font-bold px-2 py-1 rounded text-white"
                      style={{ backgroundColor: layerColors[Math.min(selectedNode.layer, layerColors.length - 2)].border }}
                    >
                      Layer {selectedNode.layer}
                    </span>
                    <span className="text-xs text-gray-500">
                      ID: {selectedNode.id}
                    </span>
                  </div>
                  
                  {selectedNode.children_count > 0 && (
                    <div className="text-xs text-gray-500">
                      {selectedNode.children_count} child nodes
                    </div>
                  )}
                  
                  {selectedNode.source_url && (
                    <a
                      href={selectedNode.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-xs text-blue-500 hover:text-blue-600"
                    >
                      <ExternalLink className="w-3 h-3" />
                      View Source
                    </a>
                  )}
                  
                  <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 border border-gray-200 dark:border-gray-700 max-h-[60vh] overflow-y-auto">
                    {loadingNodeText ? (
                      <div className="flex items-center gap-2 text-gray-500">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span className="text-sm">Loading content...</span>
                      </div>
                    ) : (
                      <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                        {selectedNodeText || selectedNode.text_preview}
                      </pre>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

