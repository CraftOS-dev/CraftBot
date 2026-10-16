// Built with the Windows .NET Framework compiler. No third-party assemblies.
// The service never imports Python from a checkout or inherits its environment.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32.SafeHandles;

class CredentialHost : ServiceBase {
    const string Name = "CraftBotCredentialHost";
    readonly object gate = new object();
    Process worker;
    SafeFileHandle workerJob;
    SafeFileHandle listener;
    volatile bool stopping;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 65536, RecursionLimit = 16 };
    // Trusted identity metadata and escaping expand an otherwise valid frame.
    const int EnvelopeLimit = 400000;
    static string Envelope(uint pid,long created,string sid,string app,object payload) {
        var serializer=new JavaScriptSerializer { MaxJsonLength=EnvelopeLimit, RecursionLimit=20 };
        string encoded=serializer.Serialize(new { peer_pid=pid,peer_created=created.ToString(System.Globalization.CultureInfo.InvariantCulture),peer_sid=sid,peer_app_sid=app,payload=payload });
        var ascii=new StringBuilder();
        foreach(char ch in encoded) { if(ch>127) ascii.Append("\\u"+((int)ch).ToString("x4")); else ascii.Append(ch); }
        if(ascii.Length>EnvelopeLimit) throw new IOException();
        return ascii.ToString();
    }
    static string Root { get { return AppDomain.CurrentDomain.BaseDirectory; } }

    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, uint revision, out IntPtr descriptor, IntPtr size);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateNamedPipe(string name, uint access, uint mode, uint instances, uint output, uint input, uint timeout, ref SECURITY_ATTRIBUTES attributes);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool ConnectNamedPipe(SafeFileHandle pipe, IntPtr overlapped);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool DisconnectNamedPipe(SafeFileHandle pipe);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CancelIoEx(SafeFileHandle pipe, IntPtr overlapped);
    [DllImport("kernel32.dll")] static extern IntPtr CreateEvent(IntPtr attributes,bool manual,bool initial,string name);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr handle,uint milliseconds);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetProcessTimes(IntPtr process,out long created,out long exited,out long system,out long user);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern SafeFileHandle CreateJobObject(IntPtr attributes,string name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(SafeFileHandle job,int kind,ref JOB_LIMITS limits,int size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(SafeFileHandle job,IntPtr process);
    [StructLayout(LayoutKind.Sequential)] struct BASIC_LIMITS { public long processTime,jobTime; public uint flags; public UIntPtr minimum,maximum; public uint active; public UIntPtr affinity; public uint priority,scheduling; }
    [StructLayout(LayoutKind.Sequential)] struct IO_COUNTERS { public ulong a,b,c,d,e,f; }
    [StructLayout(LayoutKind.Sequential)] struct JOB_LIMITS { public BASIC_LIMITS basic; public IO_COUNTERS io; public UIntPtr processMemory,jobMemory,peakProcess,peakJob; }
    [DllImport("advapi32.dll",SetLastError=true)] static extern bool ImpersonateNamedPipeClient(SafeFileHandle pipe);
    [DllImport("advapi32.dll")] static extern bool RevertToSelf();
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentThread();
    [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenThreadToken(IntPtr thread,uint rights,bool asSelf,out IntPtr token);
    [DllImport("advapi32.dll",SetLastError=true)] static extern bool GetTokenInformation(IntPtr token,int kind,IntPtr data,uint size,out uint needed);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetNamedPipeClientProcessId(SafeFileHandle pipe, out uint pid);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr value);
    [StructLayout(LayoutKind.Sequential)] struct SECURITY_ATTRIBUTES { public int size; public IntPtr descriptor; public int inherit; }
    [StructLayout(LayoutKind.Sequential)] struct OVERLAPPED { public IntPtr a,b; public uint c,d; public IntPtr signal; }

    public CredentialHost() { ServiceName=Name; CanHandleSessionChangeEvent=true; CanHandlePowerEvent=true; }
    protected override void OnStart(string[] args) {
        if (WindowsIdentity.GetCurrent().User.Value != "S-1-5-18") throw new InvalidOperationException("protected_host_required");
        Task.Factory.StartNew(Serve, TaskCreationOptions.LongRunning);
    }
    protected override void OnStop() { stopping=true; try { if(listener!=null) { CancelIoEx(listener,IntPtr.Zero); listener.Dispose(); } } catch {} Reset(); }
    protected override void OnSessionChange(SessionChangeDescription change) {
        if(change.Reason==SessionChangeReason.SessionLock || change.Reason==SessionChangeReason.SessionLogoff) Reset();
    }
    protected override bool OnPowerEvent(PowerBroadcastStatus power) { if(power==PowerBroadcastStatus.Suspend) Reset(); return true; }
    void Reset() {
        // Do not wait behind a hung resolver or owner prompt on lock/suspend.
        Process current=Interlocked.Exchange(ref worker, null);
        SafeFileHandle job=Interlocked.Exchange(ref workerJob,null);
        if(job!=null) job.Dispose();
        if(current!=null) { try { current.Kill(); current.WaitForExit(5000); } catch {} current.Dispose(); }
    }
    Process Worker() {
        if(worker!=null && !worker.HasExited) return worker;
        Reset();
        var start=new ProcessStartInfo(Path.Combine(Root,"python","python.exe"), "-I -S \""+Path.Combine(Root,"bootstrap.py")+"\"");
        start.UseShellExecute=false; start.CreateNoWindow=true; start.WorkingDirectory=Root;
        start.RedirectStandardInput=true; start.RedirectStandardOutput=true; start.RedirectStandardError=true;
        start.EnvironmentVariables.Clear();
        start.EnvironmentVariables["SYSTEMROOT"]=Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        start.EnvironmentVariables["PATH"]=Path.Combine(Root,"python");
        worker=Process.Start(start);
        workerJob=CreateJobObject(IntPtr.Zero,null);
        var limits=new JOB_LIMITS(); limits.basic.flags=0x2000|0x1000;
        // The service owns this kill-on-close supervisor. Cross-session native
        // dialogs/consumers break away and enter their own worker-owned jobs.
        if(workerJob.IsInvalid || !SetInformationJobObject(workerJob,9,ref limits,Marshal.SizeOf(typeof(JOB_LIMITS))) || !AssignProcessToJobObject(workerJob,worker.Handle)) { Reset(); throw new IOException(); }
        // Never log stderr, traceback locals, protocol data or child output.
        worker.ErrorDataReceived += delegate {}; worker.BeginErrorReadLine();
        return worker;
    }
    static string[] PipeIdentity(SafeFileHandle pipe) {
        if(!ImpersonateNamedPipeClient(pipe)) throw new IOException();
        IntPtr token=IntPtr.Zero,buffer=IntPtr.Zero;
        try {
            if(!OpenThreadToken(GetCurrentThread(),8,true,out token)) throw new IOException();
            string sid; using(var identity=new WindowsIdentity(token)) sid=identity.User.Value;
            uint needed;
            buffer=Marshal.AllocHGlobal(4);
            if(!GetTokenInformation(token,29,buffer,4,out needed)) throw new IOException();
            bool container=Marshal.ReadInt32(buffer)!=0;
            Marshal.FreeHGlobal(buffer); buffer=IntPtr.Zero;
            string app=null;
            if(container) {
                GetTokenInformation(token,31,IntPtr.Zero,0,out needed);
                if(needed<8||needed>4096) throw new IOException();
                buffer=Marshal.AllocHGlobal((int)needed);
                if(!GetTokenInformation(token,31,buffer,needed,out needed)) throw new IOException();
                app=new SecurityIdentifier(Marshal.ReadIntPtr(buffer)).Value;
            }
            return new string[] {sid,app};
        } finally {
            if(buffer!=IntPtr.Zero) Marshal.FreeHGlobal(buffer);
            if(token!=IntPtr.Zero) CloseHandle(token);
            if(!RevertToSelf()) Environment.Exit(1);
        }
    }
    void Serve() {
        while(!stopping) {
            IntPtr sd=IntPtr.Zero;
            IntPtr connected=IntPtr.Zero;
            IntPtr pendingMemory=IntPtr.Zero;
            bool connectionPending=false;
            IntPtr peerProcess=IntPtr.Zero;
            try {
                // Exact data rights exclude FILE_CREATE_PIPE_INSTANCE. Low label
                // allows AppContainer writes; kernel PID/job checks authorize use.
                if(!ConvertStringSecurityDescriptorToSecurityDescriptor("O:SYD:P(A;;GA;;;SY)(A;;0x120003;;;AU)(A;;0x120003;;;AC)S:(ML;;NW;;;LW)",1,out sd,IntPtr.Zero)) throw new IOException();
                var sa=new SECURITY_ATTRIBUTES { size=Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES)), descriptor=sd };
                if(listener==null || listener.IsClosed || listener.IsInvalid) listener=CreateNamedPipe(@"\\.\pipe\LOCAL\CraftBot.Credentials.v1", 3|0x80000|0x40000000, 8, 1,65536,65536,0,ref sa);
                if(listener.IsInvalid) throw new IOException(); // no squatting fallback
                connected=CreateEvent(IntPtr.Zero,true,false,null);
                var pending=new OVERLAPPED { signal=connected };
                pendingMemory=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(OVERLAPPED)));
                Marshal.StructureToPtr(pending,pendingMemory,false);
                if(!ConnectNamedPipe(listener,pendingMemory)) {
                    int error=Marshal.GetLastWin32Error();
                    if(error!=535) {
                        if(error!=997) throw new IOException();
                        connectionPending=true;
                        while(WaitForSingleObject(connected,1000)==258) { if(stopping) throw new IOException(); }
                    }
                }
                uint pid;
                if(!GetNamedPipeClientProcessId(listener,out pid) || pid==0) throw new IOException();
                peerProcess=OpenProcess(0x101000,false,pid);
                long created,exited,system,user;
                if(peerProcess==IntPtr.Zero || !GetProcessTimes(peerProcess,out created,out exited,out system,out user) || WaitForSingleObject(peerProcess,0)!=258) throw new IOException();
                using(var stream=new FileStream(new SafeFileHandle(listener.DangerousGetHandle(),false),FileAccess.ReadWrite,4096,true)) {
                    var incoming=Task.Factory.StartNew(()=>ReadFrame(stream));
                    if(!incoming.Wait(10000)) { CancelIoEx(listener,IntPtr.Zero); stream.Dispose(); continue; }
                    object payload=Json.DeserializeObject(incoming.Result);
                    if(WaitForSingleObject(peerProcess,0)!=258) throw new IOException();
                    string[] identity=PipeIdentity(listener);
                    // Client-dependent validation must never reset an existing
                    // worker or start one. Only worker transport failures do so.
                    string envelope=Envelope(pid,created,identity[0],identity[1],payload);
                    string response;
                    lock(gate) {
                       try {
                        var current=Worker();
                        current.StandardInput.WriteLine(envelope); current.StandardInput.Flush();
                        var answer=Task.Factory.StartNew(()=>ReadLine(current.StandardOutput));
                        // Unlock, owner authentication and private entry each
                        // have their own deadlines; permit their bounded sum.
                        if(!answer.Wait(300000)) { Reset(); throw new IOException(); }
                        response=answer.Result;
                        // Only a kernel-authenticated owner lock can request
                        // this supervisor action. Consumer results are nested
                        // and cannot forge the worker's reserved response.
                        var answered=Json.DeserializeObject(response) as Dictionary<string,object>;
                        var requested=payload as Dictionary<string,object>;
                        object requestedOp,ok,returned;
                        if(requested!=null && requested.TryGetValue("op",out requestedOp) && (requestedOp as string)=="lock" && answered!=null && answered.TryGetValue("ok",out ok) && ok is bool && (bool)ok && answered.TryGetValue("result",out returned)) {
                            var result=returned as Dictionary<string,object>; object reset;
                            if(result!=null && result.Count==1 && result.TryGetValue("reset_host",out reset) && reset is bool && (bool)reset) {
                                Reset(); response="{\"ok\":true,\"result\":{\"state\":\"locked\",\"all_profiles\":true}}";
                            }
                        }
                       } catch { Reset(); throw; }
                    }
                    WriteFrame(stream,response);
                }
            } catch {} // A disconnected/malformed client cannot reset other grants.
            finally {
                try { if(listener!=null && !listener.IsClosed && !listener.IsInvalid) { CancelIoEx(listener,IntPtr.Zero); DisconnectNamedPipe(listener); } } catch {}
                // Keep overlapped storage alive until the kernel completes it.
                if(!connectionPending || WaitForSingleObject(connected,5000)==0) {
                    if(pendingMemory!=IntPtr.Zero) Marshal.FreeHGlobal(pendingMemory);
                    if(connected!=IntPtr.Zero) CloseHandle(connected);
                }
                if(sd!=IntPtr.Zero) LocalFree(sd);
                if(peerProcess!=IntPtr.Zero) CloseHandle(peerProcess);
            }
        }
    }
    static string ReadLine(StreamReader reader) {
        var value=new StringBuilder(); int c;
        while((c=reader.Read())!=-1 && c!='\n') { if(value.Length>=65536) throw new IOException(); value.Append((char)c); }
        if(c==-1) throw new IOException(); return value.ToString();
    }
    static byte[] Exact(Stream stream,int size) { var data=new byte[size]; for(int n=0;n<size;) { int read=stream.Read(data,n,size-n); if(read==0) throw new IOException(); n+=read; } return data; }
    static string ReadFrame(Stream stream,int maximum=65536) { int size=BitConverter.ToInt32(Exact(stream,4),0); if(size<2||size>maximum) throw new IOException(); return Encoding.UTF8.GetString(Exact(stream,size)); }
    static void WriteFrame(Stream stream,string message,int maximum=65536) { byte[] data=Encoding.UTF8.GetBytes(message); if(data.Length>maximum) throw new IOException(); byte[] size=BitConverter.GetBytes(data.Length); stream.Write(size,0,4); stream.Write(data,0,data.Length); stream.Flush(); }

    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct CREDUI { public int size; public IntPtr parent; public string message; public string caption; public IntPtr banner; }
    [DllImport("credui.dll",CharSet=CharSet.Unicode)] static extern uint CredUIPromptForWindowsCredentials(ref CREDUI info,uint error,ref uint package,IntPtr input,uint inputSize,out IntPtr output,out uint size,IntPtr save,uint flags);
    [DllImport("credui.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CredUnPackAuthenticationBuffer(uint flags,IntPtr auth,uint authSize,IntPtr user,ref uint userSize,IntPtr domain,ref uint domainSize,IntPtr password,ref uint passwordSize);
    [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool LogonUser(IntPtr user,IntPtr domain,IntPtr password,uint logon,uint provider,out SafeAccessTokenHandle token);
    [DllImport("kernel32.dll",EntryPoint="RtlZeroMemory")] static extern void Zero(IntPtr buffer,UIntPtr size);
    static bool Consent(string sid,string message) {
        if(message.Length>1000 || WindowsIdentity.GetCurrent().User.Value!="S-1-5-18") return false;
        IntPtr packed=IntPtr.Zero; uint length=0,package=0;
        IntPtr user=Marshal.AllocHGlobal(2048),domain=Marshal.AllocHGlobal(2048),password=Marshal.AllocHGlobal(65536);
        try {
            var info=new CREDUI { size=Marshal.SizeOf(typeof(CREDUI)),message=message,caption="CraftBot credential authorization" };
            // Real secure desktop; no ordinary-web approval or generic prompt fallback.
            if(CredUIPromptForWindowsCredentials(ref info,0,ref package,IntPtr.Zero,0,out packed,out length,IntPtr.Zero,0x1000)!=0) return false;
            uint u=1024,d=1024,p=32768;
            if(!CredUnPackAuthenticationBuffer(0,packed,length,user,ref u,domain,ref d,password,ref p)) return false;
            SafeAccessTokenHandle token;
            if(!LogonUser(user,domain,password,2,0,out token)) return false;
            using(token) using(var identity=new WindowsIdentity(token.DangerousGetHandle())) return identity.User.Value==sid;
        } finally {
            Zero(user,(UIntPtr)2048); Zero(domain,(UIntPtr)2048); Zero(password,(UIntPtr)65536);
            Marshal.FreeHGlobal(user); Marshal.FreeHGlobal(domain); Marshal.FreeHGlobal(password);
            if(packed!=IntPtr.Zero) { Zero(packed,(UIntPtr)length); Marshal.FreeCoTaskMem(packed); }
        }
    }
    static int OwnerDialog(string[] args) {
        if(args.Length<3 || WindowsIdentity.GetCurrent().User.Value!="S-1-5-18") return 1;
        string message=Encoding.UTF8.GetString(Convert.FromBase64String(args[2]));
        if(!Consent(args[1],message)) return 1;
        if(args[0]=="--consent") return 0;
        if(args.Length==5 && (args[0]=="--view" || args[0]=="--review")) {
            using(var pipe=new NamedPipeClientStream(".",args[3],PipeDirection.InOut)) {
                pipe.Connect(5000);
                var privateJson=new JavaScriptSerializer { MaxJsonLength=2100000,RecursionLimit=4 };
                var shown=privateJson.Deserialize<Dictionary<string,string>>(ReadFrame(pipe,2100000));
                if(shown==null || shown.Count==0 || shown.Count>32) return 1;
                try { return ProtectedEntry(args[4],shown,args[0]=="--review")==null?1:0; }
                finally { shown.Clear(); }
            }
        }
        if(args.Length!=5 || args[0]!="--entry") return 1;
        Dictionary<string,string> result=ProtectedEntry(args[4]);
        if(result==null) return 1;
        // This private SYSTEM-only pipe is created by the worker. The public
        // agent transport never sees credential form values.
        using(var pipe=new NamedPipeClientStream(".",args[3],PipeDirection.InOut)) {
            var privateJson=new JavaScriptSerializer { MaxJsonLength=2100000,RecursionLimit=4 };
            pipe.Connect(5000); WriteFrame(pipe,privateJson.Serialize(result),2100000);
            pipe.ReadByte();
        }
        return 0;
    }
    [StructLayout(LayoutKind.Sequential)] struct SA { public int size; public IntPtr descriptor; public int inherit; }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct STARTUP {
        public int size; public string reserved,desktop,title; public uint x,y,width,height,xchars,ychars,fill,flags;
        public short show,reservedSize; public IntPtr reserved2,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)] struct PROCESS { public IntPtr process,thread; public uint pid,tid; }
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr CreateDesktop(string name,IntPtr device,IntPtr mode,uint flags,uint access,ref SA attributes);
    [DllImport("user32.dll",SetLastError=true)] static extern IntPtr OpenInputDesktop(uint flags,bool inherit,uint access);
    [DllImport("user32.dll")] static extern bool SwitchDesktop(IntPtr desktop);
    [DllImport("user32.dll")] static extern bool SetThreadDesktop(IntPtr desktop);
    [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool GetUserObjectInformation(IntPtr handle,int index,StringBuilder value,uint length,out uint needed);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool CreateProcess(string app,StringBuilder command,IntPtr processAttributes,IntPtr threadAttributes,bool inherit,uint flags,IntPtr environment,string directory,ref STARTUP startup,out PROCESS result);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,EntryPoint="CreateEventW",SetLastError=true)] static extern IntPtr PrivateEvent(ref SA attributes,bool manual,bool initial,string name);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern IntPtr OpenEvent(uint rights,bool inherit,string name);
    [DllImport("kernel32.dll")] static extern bool SetEvent(IntPtr handle);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr handle,uint code);

    static int EntryGuardian(string[] args) {
        if(args.Length!=5 || WindowsIdentity.GetCurrent().User.Value!="S-1-5-18") return 1;
        uint pid; long expected;
        if(!uint.TryParse(args[1],out pid)||!long.TryParse(args[2],out expected)||!args[4].StartsWith("CraftBot.Entry.")||args[3]!="Local\\"+args[4]) return 1;
        IntPtr parent=OpenProcess(0x100001|0x1000,false,pid), desktop=IntPtr.Zero,ready=IntPtr.Zero;
        try {
            long created,exited,kernel,user;
            if(parent==IntPtr.Zero || !GetProcessTimes(parent,out created,out exited,out kernel,out user)||created!=expected) return 1;
            desktop=OpenInputDesktop(0,false,0x100);
            ready=OpenEvent(2,false,args[3]);
            if(desktop==IntPtr.Zero||ready==IntPtr.Zero||!SetEvent(ready)) return 1;
            uint outcome=WaitForSingleObject(parent,90000);
            // Runs outside the UI job, with no source values or public RPC.
            // The bounded guardian survives a killed UI/worker/service.
            RestoreDesktop(desktop,args[4]);
            if(outcome!=0) TerminateProcess(parent,1);
            return 0;
        } finally {
            if(ready!=IntPtr.Zero) CloseHandle(ready);
            if(desktop!=IntPtr.Zero) CloseDesktop(desktop);
            if(parent!=IntPtr.Zero) CloseHandle(parent);
        }
    }
    static void RestoreDesktop(IntPtr original,string privateName) {
        IntPtr active=OpenInputDesktop(0,false,0x101);
        try {
            uint needed; var name=new StringBuilder(512);
            if(active!=IntPtr.Zero && GetUserObjectInformation(active,2,name,1024,out needed) && name.ToString()==privateName) SwitchDesktop(original);
        } finally { if(active!=IntPtr.Zero) CloseDesktop(active); }
    }
    static Dictionary<string,string> ProtectedEntry(string fields,Dictionary<string,string> shown=null,bool review=false) {
        IntPtr descriptor=IntPtr.Zero,desktop=IntPtr.Zero,ready=IntPtr.Zero,original=IntPtr.Zero;
        PROCESS guardian=new PROCESS();
        try {
            if(!ConvertStringSecurityDescriptorToSecurityDescriptor("O:SYD:P(A;;GA;;;SY)",1,out descriptor,IntPtr.Zero)) throw new IOException();
            var attributes=new SA { size=Marshal.SizeOf(typeof(SA)),descriptor=descriptor };
            string name="CraftBot.Entry."+Guid.NewGuid().ToString("N"),eventName="Local\\"+name;
            original=OpenInputDesktop(0,false,0x100);
            desktop=CreateDesktop(name,IntPtr.Zero,IntPtr.Zero,0,0x1ff,ref attributes);
            ready=PrivateEvent(ref attributes,true,false,eventName);
            if(ready!=IntPtr.Zero && Marshal.GetLastWin32Error()==183) throw new IOException();
            if(original==IntPtr.Zero||desktop==IntPtr.Zero||ready==IntPtr.Zero) throw new IOException();
            using(var current=Process.GetCurrentProcess()) {
                long created,exited,kernel,user;
                if(!GetProcessTimes(current.Handle,out created,out exited,out kernel,out user)) throw new IOException();
                var startup=new STARTUP { size=Marshal.SizeOf(typeof(STARTUP)),desktop="winsta0\\default" };
                string exe=Path.Combine(Root,"CredentialHost.exe");
                if(!CreateProcess(exe,new StringBuilder("\""+exe+"\" --entry-guardian "+current.Id+" "+created+" "+eventName+" "+name),IntPtr.Zero,IntPtr.Zero,false,0x01000000|0x08000000,IntPtr.Zero,Root,ref startup,out guardian)) throw new IOException();
            }
            if(WaitForSingleObject(ready,5000)!=0) throw new IOException();
            Dictionary<string,string> result=null;
            // New STA thread has no windows or hooks on the ordinary desktop.
            var thread=new Thread(delegate() {
                try {
                    if(!SetThreadDesktop(desktop)||!SwitchDesktop(desktop)) return;
                    result=EntryForm(fields,shown,review);
                } catch { result=null; }
                finally { RestoreDesktop(original,name); }
            });
            thread.SetApartmentState(ApartmentState.STA); thread.Start();
            if(!thread.Join(85000)) { RestoreDesktop(original,name); Environment.Exit(1); }
            return result;
        } finally {
            // The UI thread and bounded guardian restore only their own input
            // desktop, never a later prompt or the OS lock screen.
            if(original!=IntPtr.Zero) CloseDesktop(original);
            if(desktop!=IntPtr.Zero) CloseDesktop(desktop);
            if(ready!=IntPtr.Zero) CloseHandle(ready);
            if(descriptor!=IntPtr.Zero) LocalFree(descriptor);
            if(guardian.thread!=IntPtr.Zero) CloseHandle(guardian.thread);
            if(guardian.process!=IntPtr.Zero) CloseHandle(guardian.process);
        }
    }
    sealed class SourceTextBox : TextBox {
        protected override void WndProc(ref Message message) {
            if(message.Msg==0x300 || message.Msg==0x301) return; // No global clipboard copy/cut.
            base.WndProc(ref message);
        }
    }
    static Dictionary<string,string> EntryForm(string fields,Dictionary<string,string> shown=null,bool review=false) {
        var result=new Dictionary<string,string>();
        using(var form=new Form()) {
            form.Text=review?"CraftBot — approve exact credential request":shown==null?"CraftBot — secure credential entry":"CraftBot — private credential view"; form.Width=review?760:480; form.Height=review?680:400;
            var panel=new FlowLayoutPanel { Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown,WrapContents=false,AutoScroll=true };
            panel.Controls.Add(new Label { Text=shown==null?"Values go only to the protected vault.":"Private owner view. Clipboard copy is disabled.",AutoSize=true });
            var inputs=new Dictionary<string,TextBox>();
            foreach(string field in fields.Split(',')) {
                var box=new SourceTextBox { Width=review?690:420,UseSystemPasswordChar=!review,MaxLength=review?2100000:32768,ReadOnly=shown!=null };
                if(review) { box.Multiline=true; box.ScrollBars=ScrollBars.Both; box.WordWrap=false; box.Height=field=="Parameters"?240:60; }
                if(shown!=null) { if(!shown.ContainsKey(field)) throw new IOException(); box.Text=shown[field]; }
                inputs.Add(field,box); panel.Controls.Add(new Label { Text=field,AutoSize=true }); panel.Controls.Add(box);
                var multiline=new CheckBox { Text=shown==null?"Multiple lines (visible on this protected desktop)":"Reveal on this protected desktop",AutoSize=true };
                multiline.CheckedChanged+=delegate { box.UseSystemPasswordChar=!multiline.Checked; box.Multiline=multiline.Checked; box.AcceptsReturn=multiline.Checked; box.Height=multiline.Checked?90:24; };
                if(shown==null) box.TextChanged+=delegate { multiline.Enabled=box.TextLength==0; };
                if(!review) panel.Controls.Add(multiline);
            }
            var save=new Button { Text=review?"Approve exact request":shown==null?"Save to vault":"Close private view",AutoSize=true,DialogResult=DialogResult.OK };
            if(review) {
                save.Enabled=false;
                var confirm=new CheckBox { Text="I reviewed the destination, parameters and content notice.",AutoSize=true };
                confirm.CheckedChanged+=delegate { save.Enabled=confirm.Checked; };
                panel.Controls.Add(confirm);
                var cancel=new Button { Text="Deny",DialogResult=DialogResult.Cancel }; panel.Controls.Add(cancel); form.CancelButton=cancel;
            } else form.AcceptButton=save;
            panel.Controls.Add(save); form.Controls.Add(panel);
            if(form.ShowDialog()!=DialogResult.OK) return null;
            foreach(var input in inputs) { if(shown==null) result.Add(input.Key,input.Value.Text); input.Value.Clear(); }
        }
        return result;
    }
    [STAThread] static int Main(string[] args) {
        try { if(args.Length>0 && args[0]=="--entry-guardian") return EntryGuardian(args); if(args.Length>0) return OwnerDialog(args); ServiceBase.Run(new CredentialHost()); return 0; }
        catch { return 1; }
    }
}
