# Instrumented Social Edition (LdoD Archive) with Kieker 1.15

This repository contains the **Social Edition (LdoD Archive)** application instrumented with **Kieker 1.15** for
performance monitoring and trace analysis. The instrumentation uses **AspectJ load-time weaving** and covers **every
method and constructor of all modules** (front-end, text, virtual, search, recommendation, game, user, notification,
visual), not only the front-end.

The steps below build, run and instrument the application on **macOS** without Docker. Everything is installed inside
a working folder of your choice; no system-wide installation and no administrator password are needed.

Social Edition is licensed under the FreeBSD License by CLP / FLUC / UC and ESW / INESC-ID / IST; see
[`LICENSE.md`](LICENSE.md) (the original project README).

---

## 📥 Downloading the Original Project
The original project was cloned from:
- **GitHub Repository**: [socialsoftware/edition](https://github.com/socialsoftware/edition)
- **Branch**: `modular-monolith` (last commit `159a7b6`, 27 July 2021, *"Fixed directory bug + container port"*)

```bash
git clone --branch modular-monolith https://github.com/socialsoftware/edition.git
```
The changes described in this README (sections *Initial Build* and *Instrumentation Process*) are already applied in
this repository. To reproduce them on the original project, clone the branch above and follow the same steps.

### **Tested environment**
- macOS 26.6.2, Apple Silicon (arm64), 64 GB RAM
- Java 11 (Temurin 11.0.32), Maven 3.8.8, MySQL 8.0.44
- Kieker 1.15, AspectJ 1.9.7

---

## 🧰 Initial Build and Run (before Kieker)
Before integrating Kieker, the project was built and run in its original form to make sure it works on macOS.
In all commands, `EDITION` is the project folder and `WORK` is a folder for the tools, the database and the data:
```bash
export EDITION=<path to this repository>
export WORK=<path to a working folder>
```

### **Step 1: Install Java 11, Maven and MySQL locally**
Edition requires **Java 11** (its Dockerfile uses `maven:3.6.3-jdk-11`).
```bash
mkdir -p $WORK/tools && cd $WORK/tools
curl -L -o jdk11.tar.gz "https://api.adoptium.net/v3/binary/latest/11/ga/mac/aarch64/jdk/hotspot/normal/eclipse"
curl -L -o maven.tar.gz "https://archive.apache.org/dist/maven/maven-3/3.8.8/binaries/apache-maven-3.8.8-bin.tar.gz"
curl -L -o mysql.tar.gz "https://cdn.mysql.com/Downloads/MySQL-8.0/mysql-8.0.44-macos15-arm64.tar.gz"
tar xzf jdk11.tar.gz && tar xzf maven.tar.gz && tar xzf mysql.tar.gz && mv mysql-8.0.44-macos15-arm64 mysql && rm *.tar.gz
```
(on an Intel Mac use `x64` instead of `aarch64`, and the MySQL `x86_64` archive)

Set these in every new terminal:
```bash
export JAVA_HOME=$(ls -d $WORK/tools/jdk-11*/Contents/Home)
export PATH=$JAVA_HOME/bin:$WORK/tools/apache-maven-3.8.8/bin:$PATH
```

### **Step 2: Set up the MySQL database**
Edition stores its data in a MySQL database (`docker-compose.yml`: database `edition`, user/password `darfo`/`darfo`).
```bash
mkdir -p $WORK/mysql-data $WORK/logs
cat > $WORK/tools/my.cnf <<EOF
[mysqld]
basedir=$WORK/tools/mysql
datadir=$WORK/mysql-data
port=3306
bind-address=127.0.0.1
socket=$WORK/tools/mysql.sock
mysqlx=OFF
default_authentication_plugin=mysql_native_password
character-set-server=utf8mb4
sql_mode=
log-error=$WORK/logs/mysqld.err
[client]
socket=$WORK/tools/mysql.sock
EOF
$WORK/tools/mysql/bin/mysqld --defaults-file=$WORK/tools/my.cnf --initialize-insecure        # only once
nohup $WORK/tools/mysql/bin/mysqld --defaults-file=$WORK/tools/my.cnf > /dev/null 2>&1 &      # start MySQL
$WORK/tools/mysql/bin/mysql --defaults-file=$WORK/tools/my.cnf -uroot -e "
  CREATE DATABASE edition CHARACTER SET utf8mb4;
  CREATE USER 'darfo'@'localhost' IDENTIFIED WITH mysql_native_password BY 'darfo';
  CREATE USER 'darfo'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY 'darfo';
  GRANT ALL ON edition.* TO 'darfo'@'localhost'; GRANT ALL ON edition.* TO 'darfo'@'127.0.0.1'; FLUSH PRIVILEGES;"
```

#### **Issue: Old MySQL driver**
- Edition uses `mysql-connector-java` **5.1.47** (required by the Fenix Framework), which cannot log in with MySQL 8's
  default password method (`caching_sha2_password`).
- **Resolution:** the server default and the `darfo` user use `mysql_native_password` (see `my.cnf` and `CREATE USER`).

### **Step 3: Configure Edition**
Create the three configuration files in `front-end/src/main/resources/` from the `*.example` files:
```bash
cd $EDITION/front-end/src/main/resources
cp secrete.properties.example secrete.properties
sed -e 's/^dbUsername=.*/dbUsername=darfo/' -e 's/^dbPassword=.*/dbPassword=darfo/' \
  fenix-framework.properties.example > fenix-framework.properties
sed -e "s#PATH/ldod/#$WORK/ldod/#g" -e '/^\/\//d' specific.properties.example > specific.properties
for d in corpus/files inters facsimiles encoding export indexer tests social/aware load; do mkdir -p $WORK/ldod/$d; done
```
- `fenix-framework.properties`: the database connection. The `dbAlias` must point to `localhost` (the commented
  alias with host `db` is only for the Docker image).
- `specific.properties`: Edition's data folders. On Linux they are under `/opt/ldod/`; on a Mac `/opt` needs an
  administrator password, so they are placed in `$WORK/ldod/`.
- `secrete.properties`: keys for social login; they can stay empty.

### **Step 4: Build Edition**
Edition depends on the **Fenix Framework 2.8.0**, which is published only in the FenixEdu repository
(`https://repo.fenixedu.org/fenixedu-maven-repository`), not on Maven Central.

#### **Issue: Spring repository requires a login**
- The root `pom.xml` lists `https://repo.spring.io/libs-release` first. It now answers **401 (login required)**, so
  Maven falls back to the slow FenixEdu repository for every ordinary library.
- **Resolution:** a Maven `settings.xml` that redirects the Spring repository to Maven Central (all libraries it served
  are there). It also keeps the downloaded libraries in `$WORK/tools/m2`:
```bash
cat > $WORK/tools/settings.xml <<EOF
<settings>
  <localRepository>$WORK/tools/m2</localRepository>
  <mirrors>
    <mirror><id>central-for-spring</id><mirrorOf>spring-releases,spring-milestones,spring-snapshots</mirrorOf>
      <url>https://repo.maven.apache.org/maven2</url></mirror>
  </mirrors>
</settings>
EOF
```

#### **Issue: `repo.fenixedu.org` "could not resolve host"**
- On some networks `curl` cannot resolve `repo.fenixedu.org` (an alias of `fenixedu-repo.tecnico.ulisboa.pt`), which
  makes the repository look offline. The repository is **online**, and Java/Maven resolved it without problems.
- **Resolution (only if Maven reports that it cannot resolve the host):** add this line to `/etc/hosts` (needs `sudo`):
  `193.136.128.72 repo.fenixedu.org`

Build (tests skipped):
```bash
cd $EDITION && mvn -B -s $WORK/tools/settings.xml -DskipTests install
```
The runnable application is `front-end/target/ldod.jar` (Spring Boot jar).

### **Step 5: Run Edition**
```bash
cd $EDITION/front-end && java -jar target/ldod.jar
```
- Open **http://localhost:8080/?lang=en** (without `?lang=en` the site is in Portuguese).
- Log in with user **`ars`**, password **`mar39`** (created at the first startup).
- On startup Edition creates its tables and loads its editions and users. Fragment texts are loaded on the admin page
  (*Admin → Load*), e.g. the sample TEI files in `front-end/src/test/resources/files/`.
- Harmless messages in the log: MySQL SSL warnings.

---

## 🛠 Instrumentation Process

# Instrumentation of Social Edition with Kieker 1.15

> **Reference Guide Followed:**
> 🔗 **[How to Perform Trace Analysis - Kieker Monitoring](https://kieker-monitoring.readthedocs.io/en/latest/tutorials/How-to-perform-Trace-Analysis.html#prerequisites)**.

The instrumentation uses **AspectJ load-time weaving**: the application is started with the AspectJ agent
(`-javaagent:aspectjweaver-1.9.7.jar`), which adds Kieker's `OperationExecutionAspectFull` probe to every class
matched in `META-INF/aop.xml` while the class is loaded. No probes are compiled into the classes, and Edition's own
code is not changed. The following modifications were made:

### **1. Kieker and AspectJ dependencies**
Added to `front-end/pom.xml`, so that Kieker is packaged in `ldod.jar`:
```xml
<dependency>
    <groupId>net.kieker-monitoring</groupId>
    <artifactId>kieker</artifactId>
    <version>1.15</version>
</dependency>
<dependency>
    <groupId>org.aspectj</groupId>
    <artifactId>aspectjrt</artifactId>
    <version>1.9.7</version>
</dependency>
```

### **2. `aop.xml`: instrument all modules**
New file `front-end/src/main/resources/META-INF/aop.xml`:
```xml
<!DOCTYPE aspectj PUBLIC "-//AspectJ//DTD//EN" "http://www.aspectj.org/dtd/aspectj_1_5_0.dtd">
<aspectj>
    <weaver options="-Xset:weaveJavaxPackages=true">
        <!-- every class of every module: pt.ist.socialsoftware.edition.{ldod.frontend,text,virtual,search,...} -->
        <include within="pt.ist.socialsoftware.edition..*"/>
        <!-- proxy classes generated at runtime by Spring (CGLIB) are not application code and fail verification when woven -->
        <exclude within="*..*CGLIB*"/>
    </weaver>
    <aspects>
      <aspect name="kieker.monitoring.probe.aspectj.operationExecution.OperationExecutionAspectFull"/>
    </aspects>
</aspectj>
```
`OperationExecutionAspectFull` records the execution of **all methods and constructors** (including getters and
setters) of the included classes.

#### **Issue: `VerifyError` at startup**
- With only the `include` line, the application does not start (`java.lang.VerifyError` in a Spring proxy class).
- **Resolution:** `<exclude within="*..*CGLIB*"/>`. See [*Why including all modules needed two fixes*](#-why-including-all-modules-needed-two-fixes).

### **3. `kieker.monitoring.properties`: Kieker writer settings**
Content of `front-end/src/main/resources/META-INF/kieker.monitoring.properties`. **Before building, replace
`<KIEKER_LOG_DIR>` with an existing absolute path**; the traces are written there:
```properties
kieker.monitoring.name=KIEKER
kieker.monitoring.debug=false
kieker.monitoring.enabled=true
kieker.monitoring.hostname=
kieker.monitoring.metadata=true
kieker.monitoring.setLoggingTimestamp=true
kieker.monitoring.useShutdownHook=true
kieker.monitoring.jmx=false
kieker.monitoring.periodicSensorsExecutorPoolSize=0
kieker.monitoring.adaptiveMonitoring.enabled=false
kieker.monitoring.timer=kieker.monitoring.timer.SystemNanoTimer
kieker.monitoring.timer.SystemMilliTimer.unit=0
kieker.monitoring.writer=kieker.monitoring.writer.filesystem.FileWriter
kieker.monitoring.writer.filesystem.FileWriter.customStoragePath=<KIEKER_LOG_DIR>
kieker.monitoring.writer.filesystem.FileWriter.charsetName=UTF-8
kieker.monitoring.writer.filesystem.FileWriter.maxEntriesInFile=25000
kieker.monitoring.writer.filesystem.FileWriter.maxLogSize=-1
kieker.monitoring.writer.filesystem.FileWriter.maxLogFiles=-1
kieker.monitoring.writer.filesystem.FileWriter.mapFileHandler=kieker.monitoring.writer.filesystem.TextMapFileHandler
kieker.monitoring.writer.filesystem.TextMapFileHandler.flush=true
kieker.monitoring.writer.filesystem.TextMapFileHandler.compression=kieker.monitoring.writer.compression.NoneCompressionFilter
kieker.monitoring.writer.filesystem.FileWriter.logFilePoolHandler=kieker.monitoring.writer.filesystem.RotatingLogFilePoolHandler
kieker.monitoring.writer.filesystem.FileWriter.logStreamHandler=kieker.monitoring.writer.filesystem.TextLogStreamHandler
kieker.monitoring.writer.filesystem.TextLogStreamHandler.compression=kieker.monitoring.writer.compression.NoneCompressionFilter
kieker.monitoring.writer.filesystem.FileWriter.flush=true
kieker.monitoring.writer.filesystem.FileWriter.bufferSize=81920
kieker.monitoring.core.controller.WriterController.RecordQueueFQN=java.util.concurrent.ArrayBlockingQueue
kieker.monitoring.core.controller.WriterController.RecordQueueSize=1000000
kieker.monitoring.core.controller.WriterController.RecordQueueInsertBehavior=1
```

#### **Issue: The application freezes after a few minutes of use**
- With all modules instrumented, every request hangs after a few minutes (Kieker's default record queue deadlocks).
- **Resolution:** the last three lines above (a standard thread-safe queue). See
  [*Why including all modules needed two fixes*](#-why-including-all-modules-needed-two-fixes).

### **4. Build and run with the AspectJ agent**
```bash
mkdir -p <KIEKER_LOG_DIR>
curl -L -o $WORK/tools/aspectjweaver-1.9.7.jar https://repo1.maven.org/maven2/org/aspectj/aspectjweaver/1.9.7/aspectjweaver-1.9.7.jar
cd $EDITION && mvn -B -s $WORK/tools/settings.xml -DskipTests install
cd $EDITION/front-end && java -javaagent:$WORK/tools/aspectjweaver-1.9.7.jar -jar target/ldod.jar
```
- The startup log shows `Queue type: class java.util.concurrent.ArrayBlockingQueue`.
- While the application is used, `<KIEKER_LOG_DIR>/kieker-<date>-UTC--KIEKER/` receives `.dat` files. Each
  operation-execution record (`$1;...`) contains the full method signature, e.g.
  `public ... pt.ist.socialsoftware.edition.text.domain.Fragment.getTitle()`.
- After changing only `aop.xml` or `kieker.monitoring.properties`, rebuilding the front-end is enough:
  `mvn -B -o -s $WORK/tools/settings.xml -pl front-end -DskipTests package`

---

## 📝 Why Including All Modules Needed Two Fixes
*(for future reference)*

To weave all methods of all modules, `aop.xml` includes every package of the application
(`<include within="pt.ist.socialsoftware.edition..*"/>`). With this full weaving, the application broke in two
different ways, one after the other. Both problems and their fixes are described below.

### **Problem 1: the application does not start**
**What happens.** With only
```xml
<include within="pt.ist.socialsoftware.edition..*"/>
```
Spring Boot stops during startup with `Application run failed`, caused by
```
java.lang.VerifyError: Inconsistent stackmap frames at branch target 77
  Location: pt/ist/socialsoftware/edition/ldod/frontend/config/Application$$EnhancerBySpringCGLIB$$7d26a625.signInAdapter()...
  Reason: Current frame's stack size doesn't match stackmap.
```
**Why.** The `include` pattern matches classes by name. Besides Edition's own classes, it also matches classes that
Spring generates in memory at startup: for every `@Configuration` class, Spring creates a subclass (proxy) with CGLIB,
named after the original class plus `$$EnhancerBySpringCGLIB$$<hash>`, in the same package. The AspectJ weaver
instruments these generated classes as well, and the modified bytecode is rejected by the JVM's bytecode verifier.

**What led to the fix.** The class named in the `VerifyError` is not a class of Edition's source code but a Spring
proxy (`$$EnhancerBySpringCGLIB$$`). Such proxies only forward calls to the original class, which is instrumented
anyway, so they do not need a probe.

**Fix.** `<exclude within="*..*CGLIB*"/>`. The application then starts, and traces contain classes of all modules.

### **Problem 2: the application freezes after a few minutes**
**What happens.** The application starts and works, but after a few minutes of use (in our case on the reading
pages, which call many small methods) every request hangs: the browser waits forever, the application uses no CPU,
and the log shows no errors. Only a restart helps.

**How it was diagnosed.** A thread dump of the running application (`jstack <pid>`) showed:
- all web request threads (`http-nio-8080-exec-*`) waiting in
  ```
  kieker.monitoring.queue.putstrategy.SPBlockingPutStrategy.backoffOffer
  kieker.monitoring.queue.BlockingQueueDecorator.put
  kieker.monitoring.queue.behavior.BlockOnFailedInsertBehavior.insert
  kieker.monitoring.core.controller.WriterController.newMonitoringRecord
  kieker.monitoring.probe.aspectj.operationExecution.AbstractOperationExecutionAspect.afterOperation
  ```
  i.e., each probe waits for free space in Kieker's record queue (queue full);
- Kieker's writer thread (`MonitoringWriterThread`, which takes records from the queue and writes them to disk)
  waiting in `kieker.monitoring.queue.takestrategy.SCBlockingTakeStrategy.waitPoll`, i.e., waiting for records
  (queue empty).

The request threads wait for the writer and the writer waits for the request threads: a deadlock. The startup log
shows Kieker's default queue: `BlockingQueueDecorator` around `org.jctools.queues.MpscArrayQueue`, capacity 10,000,
with `BlockOnFailedInsertBehavior`.

**Why.** `SP` and `SC` stand for *single producer* and *single consumer*: these blocking strategies coordinate one
thread putting records with one thread taking them. In a web application many request threads put records at the
same time; under a high record rate a wake-up signal between the threads is lost, and both sides wait for each other.
With all modules instrumented (including many small getters and setters), the record rate is high: the
10,000-record queue fills within seconds and the deadlock appears.

**What led to the fix.** Kieker's own configuration lists the queue implementations it supports
(`org.jctools.queues.MpscArrayQueue`, `java.util.concurrent.LinkedBlockingQueue`,
`java.util.concurrent.ArrayBlockingQueue`). `ArrayBlockingQueue` is a standard Java queue that is safe for any number
of producer threads and blocks correctly by itself, so Kieker uses it without the single-producer/single-consumer
strategies.

**Fix.** In `kieker.monitoring.properties`:
```properties
kieker.monitoring.core.controller.WriterController.RecordQueueFQN=java.util.concurrent.ArrayBlockingQueue
kieker.monitoring.core.controller.WriterController.RecordQueueSize=1000000
kieker.monitoring.core.controller.WriterController.RecordQueueInsertBehavior=1
```
The startup log then shows `Queue type: class java.util.concurrent.ArrayBlockingQueue`. The larger capacity absorbs
bursts of records; insert behavior `1` (the application waits when the queue is full) is kept, so no record is dropped
(behavior `2` would drop records, and `0` would stop monitoring). With this setting, the application ran through
startup and several complete runs through all features without freezing.

> **Tip:** if an instrumented application hangs, take a thread dump with `jstack <pid>` (the process id is shown by
> `jps` or `pgrep -f ldod.jar`). Threads waiting inside `kieker.monitoring...` point to Kieker's queue.

---

## ✅ Confirming that All Methods Are Instrumented
A trace only contains the methods that were executed, so the instrumentation is checked on the weaver itself.
Starting the application with AspectJ's weave information writes one log line per instrumented method or constructor:
```bash
cd $EDITION/front-end && java -Dorg.aspectj.weaver.showWeaveInfo=true -Daj.weaving.verbose=true \
  -javaagent:$WORK/tools/aspectjweaver-1.9.7.jar -jar target/ldod.jar > $WORK/logs/app_weaveinfo.log 2>&1
```
Use the application, stop it, and compare the instrumented methods with all methods declared in the source:
```bash
python3 -m venv $WORK/tools/pyenv && $WORK/tools/pyenv/bin/pip install javalang
$WORK/tools/pyenv/bin/python check_instrumentation.py $EDITION $WORK/logs/app_weaveinfo.log $WORK/instrumentation_check
```
`instrumentation_check.txt` lists, per module and per layer, how many methods are *woven*, *not woven although the
class was loaded*, in a *class never loaded*, or have *no body* (abstract/interface methods, which have nothing to
instrument). `instrumentation_check.csv` has one row per method.

**Result** (this repository built as described above; application startup, loading the sample TEI files on the admin
page, and opening the main pages: fragments, sources, editions, reading, search, virtual editions, about):

| Module | Woven | NOT woven (class loaded) | Class never loaded | No body |
|---|---|---|---|---|
| front-end | 668 | **0** | 77 | 0 |
| text | 709 | **0** | 88 | 29 |
| virtual | 696 | **0** | 168 | 3 |
| user | 141 | **0** | 26 | 0 |
| game | 125 | **0** | 45 | 0 |
| recommendation | 97 | **0** | 40 | 12 |
| search | 55 | **0** | 112 | 3 |
| notification | 12 | **0** | 0 | 1 |
| api | 33 | **0** | 25 | 0 |

The traces of the same run contain records from every module (`pt.ist.socialsoftware.edition.ldod` front-end, `text`,
`virtual`, `user`, `recommendation`, `notification`, `game`, `search`, `api`).

Every method and constructor of every loaded class carries the Kieker probe, in all modules and all layers (api, dto,
domain, feature, utils, controllers). Load-time weaving instruments a class when it is loaded, so methods of classes
that were never loaded are not woven, and they cannot appear in a trace either.

---
###### Note for future reference

> - The FenixEdu Maven repository (`repo.fenixedu.org`) is still online; "could not resolve host" came from the local DNS setup.
> - No public Docker image of Edition exists; the `docker-ldod` image in `docker-compose.yml` is built locally.
> - Every branch of `socialsoftware/edition` (`master`, `modular-monolith`, `kieker-instrumented`, `microservices`) needs Fenix Framework 2.8.0 from the FenixEdu repository.
> - Java 11 is required.
> - The `aspectj-maven-plugin` (compile-time weaving) is not used: load-time weaving with the agent instruments the classes of all modules, including those packaged as separate jars inside `ldod.jar`.
> - Instrumenting all methods produces large traces (hundreds of MB for a few minutes of use).
