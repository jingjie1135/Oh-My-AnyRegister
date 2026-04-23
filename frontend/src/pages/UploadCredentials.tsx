import { useState, useEffect } from 'react'
import { Plus, Trash2, Link, Activity, Send } from 'lucide-react'
import { apiFetch } from '@/lib/utils'

export default function UploadCredentials() {
  const [channels, setChannels] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [channelForm, setChannelForm] = useState({
    name: '',
    channel_type: 'cpa',
    api_url: '',
    api_key: '',
    is_enabled: true
  })

  const [testResult, setTestResult] = useState<string | null>(null)
  const [pushResult, setPushResult] = useState<any | null>(null)
  
  // mock asset fetching state
  const [selectedChannelId, setSelectedChannelId] = useState<number | null>(null)
  const [accounts, setAccounts] = useState<any[]>([])
  
  useEffect(() => {
    fetchChannels()
    fetchAccounts()
  }, [])

  const fetchChannels = async () => {
    try {
      setLoading(true)
      const data = await apiFetch('/upload-channels')
      setChannels(data || [])
    } finally {
      setLoading(false)
    }
  }

  const fetchAccounts = async () => {
    try {
      const data = await apiFetch('/accounts?page_size=200')
      setAccounts(data.items || [])
    } catch (e) {
      console.error("Failed to fetch accounts", e)
    }
  }

  const handleCreateChannel = async () => {
    try {
      await apiFetch('/upload-channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(channelForm)
      })
      setChannelForm({ name: '', channel_type: 'cpa', api_url: '', api_key: '', is_enabled: true })
      fetchChannels()
    } catch (e) {
      alert("创建通道失败")
    }
  }

  const handleDeleteChannel = async (id: number) => {
    if (!window.confirm("确定删除该分发通道？")) return
    try {
      await apiFetch(`/upload-channels/${id}`, { method: 'DELETE' })
      fetchChannels()
    } catch (e) {
      alert("删除失败")
    }
  }

  const handleTestConnection = async (id: number) => {
    setTestResult('测试中...')
    try {
      const res = await apiFetch(`/upload-channels/${id}/test`, { method: 'POST' })
      setTestResult(res.success ? `✅ 成功: ${res.message}` : `❌ 失败: ${res.message}`)
      setTimeout(() => setTestResult(null), 5000)
    } catch (e: any) {
      setTestResult(`❌ 异常: ${e.message}`)
      setTimeout(() => setTestResult(null), 5000)
    }
  }

  const handleBatchPush = async () => {
    if (!selectedChannelId) {
      alert('请先选择一个通道')
      return
    }
    
    // Default selecting all valid accounts currently on the screen roughly
    const ids = accounts.map(a => a.id)
    if (!ids.length) {
      alert('无可上传资源')
      return
    }

    setPushResult('正在执行推送任务，请稍候...')
    try {
      const res = await apiFetch(`/upload-channels/${selectedChannelId}/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_ids: ids, channel_id: selectedChannelId })
      })
      setPushResult(`✅ 成功 [${res.success_count}], 失败 [${res.failed_count}], 跳过 [${res.skipped_count}]`)
    } catch (e: any) {
      setPushResult(`❌ 推送异常: ${e.message}`)
    }
  }

  return (
    <div className="flex h-full flex-col space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)]">凭据分发中心</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">统一管理旗下各类平台（CPA / Sub2API / Team Manager / NewAPI / Adobe2API / Flow2API）的分发策略</p>
        </div>
      </header>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 min-h-0 flex-1">
        {/* Left Side: Channels Config */}
        <div className="flex flex-col space-y-4 rounded-3xl border border-[var(--border-soft)] bg-[var(--hero-bg)] p-5">
           <h2 className="text-sm font-semibold flex items-center gap-2"><Link className="w-4 h-4 text-emerald-400"/> 通道管理</h2>
           
           <div className="flex space-x-2">
             <input className="input w-1/3" placeholder="渠道名称" value={channelForm.name} onChange={e => setChannelForm({...channelForm, name: e.target.value})} />
             <select className="input w-1/4" value={channelForm.channel_type} onChange={e => setChannelForm({...channelForm, channel_type: e.target.value})}>
                <option value="cpa">CPA</option>
                <option value="sub2api">Sub2API</option>
                <option value="team_manager">Team Manager</option>
                <option value="new_api">New-API</option>
                <option value="adobe2api">Adobe2API</option>
                <option value="flow2api">Flow2API</option>
             </select>
           </div>
           <div className="flex space-x-2">
              <input className="input flex-1" placeholder="API URL" value={channelForm.api_url} onChange={e => setChannelForm({...channelForm, api_url: e.target.value})} />
              <input className="input flex-1" placeholder="API Key" type="password" value={channelForm.api_key} onChange={e => setChannelForm({...channelForm, api_key: e.target.value})} />
              <button 
                className="btn bg-[var(--accent)] text-white hover:opacity-90 pl-3 pr-4 flex items-center gap-1.5"
                onClick={handleCreateChannel}
              >
                 <Plus className="w-4 h-4"/> 新增
              </button>
           </div>

           <div className="mt-4 flex-1 overflow-y-auto space-y-3">
              {loading && <div className="text-xs text-[var(--text-muted)]">加载中...</div>}
              {channels.map(ch => (
                <div key={ch.id} className="flex flex-col rounded-xl border border-[var(--border-soft)] p-3 bg-[var(--bg-active)]">
                  <div className="flex justify-between items-center mb-1">
                     <span className="font-medium text-sm text-[var(--text-primary)]">{ch.name} <span className="ml-1 text-[10px] bg-[var(--accent)]/10 text-[var(--accent)] px-1.5 py-0.5 rounded-full">{ch.channel_type}</span></span>
                     <div className="flex gap-2">
                       <button onClick={() => handleTestConnection(ch.id)} className="text-xs flex items-center gap-1 text-emerald-400 hover:text-emerald-300 transition-colors">
                          <Activity className="w-3 h-3"/> 探活
                       </button>
                       <button onClick={() => handleDeleteChannel(ch.id)} className="text-xs flex items-center gap-1 text-rose-400 hover:text-rose-300 transition-colors">
                          <Trash2 className="w-3 h-3"/> 删除
                       </button>
                     </div>
                  </div>
                  <div className="text-[11px] text-[var(--text-muted)] font-mono truncate">{ch.api_url}</div>
                </div>
              ))}
           </div>
           
           {testResult && (
             <div className="mt-2 p-3 text-xs rounded-lg bg-[var(--border)] border border-[var(--border-soft)] text-[var(--text-primary)]">
               {testResult}
             </div>
           )}
        </div>

        {/* Right Side: Execution Dashboard */}
        <div className="flex flex-col space-y-4 rounded-3xl border border-[var(--border-soft)] bg-[var(--hero-bg)] p-5">
           <h2 className="text-sm font-semibold flex items-center gap-2"><Send className="w-4 h-4 text-purple-400"/> 全局下发集控</h2>
           
           <div className="flex flex-col gap-4">
              <div>
                 <label className="text-xs text-[var(--text-muted)] mb-1 block">目标下发通道</label>
                 <select 
                   className="input w-full"
                   value={selectedChannelId || ""}
                   onChange={e => setSelectedChannelId(Number(e.target.value))}
                 >
                    <option value="" disabled>-- 选取并装载目标节点 --</option>
                    {channels.map(ch => (
                       <option key={ch.id} value={ch.id}>[{ch.channel_type}] {ch.name}</option>
                    ))}
                 </select>
              </div>

              <div className="p-4 rounded-xl bg-orange-500/10 border border-orange-500/20">
                 <p className="text-xs text-orange-400/90 leading-relaxed font-mono">
                    系统探测到数据库当前存放有效资产：<b className="text-orange-300">{accounts.length}</b> 个。<br/>
                    请先点击右侧“立即执行投递”，所有资产都将被打包推送到对应的目标通道中解析。如果是批处理通道，这将只占用 1 个请求开销。
                 </p>
                 <button 
                  className="mt-4 w-full btn bg-purple-600 hover:bg-purple-500 text-white shadow-[0_0_20px_rgba(147,51,234,0.3)] border-transparent transition-all"
                  onClick={handleBatchPush}
                 >
                    <Send className="w-4 h-4 mr-2" /> 立即执行投递任务
                 </button>
              </div>

              {pushResult && (
                 <div className="mt-2 p-4 text-xs rounded-xl bg-[#090b0e] border border-[var(--border-soft)] text-emerald-400 font-mono break-all whitespace-pre-wrap">
                   {pushResult}
                 </div>
              )}
           </div>
        </div>
      </div>
    </div>
  )
}
