# Candidate report

Deterministic shortlists produced by `src/candidates.py`. Inspection
aid only -- not consumed by the pipeline and not ground truth.

Shortlist size: top 5.  Weights: name 0.50  ref 0.20  type 0.12  desc 0.10  fuzzy 0.08

## emp_master -> employees

19 source columns, 25 destination leaf paths.

```
emp_id  (INT PRIMARY KEY)

  1. 0.599  _id                        ObjectId name 0.50  ref 1.00  type 1.00  desc 0.00  fuzzy 0.36
  2. 0.360  location.locationId        ObjectId name 0.33  ref 0.00  type 1.00  desc 0.33  fuzzy 0.50
  3. 0.350  employment.managerId       ObjectId name 0.31  ref 0.00  type 1.00  desc 0.33  fuzzy 0.53
  4. 0.335  department.departmentId    ObjectId name 0.33  ref 0.00  type 1.00  desc 0.33  fuzzy 0.18
  5. 0.256  employeeCode               String   name 0.33  ref 0.00  type 0.00  desc 0.25  fuzzy 0.80
```

```
emp_cd  (VARCHAR(20) UNIQUE NOT NULL)  -- human-readable employee code

  1. 0.800  employeeCode               String   name 1.00  ref 0.00  type 1.00  desc 1.00  fuzzy 1.00
  2. 0.413  department.code            String   name 0.45  ref 0.00  type 1.00  desc 0.25  fuzzy 0.53
  3. 0.413  location.code              String   name 0.45  ref 0.00  type 1.00  desc 0.25  fuzzy 0.53
  4. 0.150  contact.phone              String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.38
  5. 0.147  location.country           String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.33
```

```
f_name  (VARCHAR(50) NOT NULL)

  1. 0.650  fullName.firstName         String   name 0.90  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.391  department.name            String   name 0.45  ref 0.00  type 1.00  desc 0.00  fuzzy 0.57
  3. 0.391  location.name              String   name 0.45  ref 0.00  type 1.00  desc 0.00  fuzzy 0.57
  4. 0.333  fullName.lastName          String   name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.74
  5. 0.150  employment.status          String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.38
```

```
l_name  (VARCHAR(50) NOT NULL)

  1. 0.650  fullName.lastName          String   name 0.90  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.394  department.name            String   name 0.45  ref 0.00  type 1.00  desc 0.00  fuzzy 0.62
  3. 0.394  location.name              String   name 0.45  ref 0.00  type 1.00  desc 0.00  fuzzy 0.62
  4. 0.333  fullName.firstName         String   name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.74
  5. 0.152  employment.status          String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.40
```

```
dob  (DATE)

  1. 0.310  employment.endDate         ISODate  name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.44
  2. 0.306  employment.startDate       ISODate  name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.40
  3. 0.160  meta.createdAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.50
  4. 0.160  meta.updatedAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.50
  5. 0.048  fullName.firstName         String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.60
```

```
hire_dt  (DATETIME)

  1. 0.650  employment.startDate       ISODate  name 0.90  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.319  employment.endDate         ISODate  name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.56
  3. 0.160  meta.updatedAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.50
  4. 0.150  meta.createdAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.38
  5. 0.046  compensation.baseSalary    Number   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.57
```

```
term_dt  (DATETIME)  -- null if still active

  1. 0.700  employment.endDate         ISODate  name 0.90  ref 0.00  type 1.00  desc 0.50  fuzzy 1.00
  2. 0.319  employment.startDate       ISODate  name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.56
  3. 0.166  meta.updatedAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.57
  4. 0.154  meta.createdAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.43
  5. 0.123  employment.status          String   name 0.00  ref 0.00  type 0.00  desc 1.00  fuzzy 0.29
```

```
dept_id  (INT FK->dept_info.dept_id)

  1. 0.933  department.departmentId    ObjectId name 1.00  ref 1.00  type 1.00  desc 0.33  fuzzy 1.00
  2. 0.391  _id                        ObjectId name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.27
  3. 0.333  location.locationId        ObjectId name 0.33  ref 0.00  type 1.00  desc 0.33  fuzzy 0.17
  4. 0.321  employment.managerId       ObjectId name 0.31  ref 0.00  type 1.00  desc 0.33  fuzzy 0.17
  5. 0.122  compensation.baseSalary    Number   name 0.00  ref 0.00  type 0.85  desc 0.00  fuzzy 0.25
```

```
mgr_emp_id  (INT FK->emp_master.emp_id)

  1. 0.721  employment.managerId       ObjectId name 0.62  ref 1.00  type 1.00  desc 0.33  fuzzy 0.74
  2. 0.313  location.locationId        ObjectId name 0.25  ref 0.00  type 1.00  desc 0.33  fuzzy 0.43
  3. 0.303  _id                        ObjectId name 0.33  ref 0.00  type 1.00  desc 0.00  fuzzy 0.21
  4. 0.289  department.departmentId    ObjectId name 0.25  ref 0.00  type 1.00  desc 0.33  fuzzy 0.13
  5. 0.201  employeeCode               String   name 0.25  ref 0.00  type 0.00  desc 0.25  fuzzy 0.64
```

```
job_lvl_cd  (VARCHAR(10))  -- e.g. L1, L2, IC3, M1

  1. 0.591  employment.jobLevel        String   name 0.62  ref 0.00  type 1.00  desc 1.00  fuzzy 0.78
  2. 0.310  department.code            String   name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.44
  3. 0.310  location.code              String   name 0.31  ref 0.00  type 1.00  desc 0.00  fuzzy 0.44
  4. 0.283  employeeCode               String   name 0.25  ref 0.00  type 1.00  desc 0.00  fuzzy 0.48
  5. 0.137  contact.email              String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.21
```

```
base_sal  (DECIMAL(12,2))

  1. 0.700  compensation.baseSalary    Number   name 1.00  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.067  compensation.currency      String   name 0.10  ref 0.00  type 0.00  desc 0.00  fuzzy 0.21
  3. 0.046  employment.startDate       ISODate  name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.57
  4. 0.025  employment.endDate         ISODate  name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.32
  5. 0.024  employment.jobLevel        String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.30
```

```
sal_currency  (CHAR(3))  -- ISO 4217, e.g. USD

  1. 0.601  compensation.currency      String   name 0.65  ref 0.00  type 1.00  desc 1.00  fuzzy 0.70
  2. 0.246  compensation.baseSalary    Number   name 0.33  ref 0.00  type 0.25  desc 0.00  fuzzy 0.62
  3. 0.190  location.country           String   name 0.00  ref 0.00  type 1.00  desc 0.33  fuzzy 0.45
  4. 0.144  contact.email              String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.30
  5. 0.139  employeeCode               String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.23
```

```
work_email  (VARCHAR(120) UNIQUE)

  1. 0.398  contact.email              String   name 0.45  ref 0.00  type 1.00  desc 0.00  fuzzy 0.67
  2. 0.143  employeeCode               String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.29
  3. 0.139  location.country           String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.24
  4. 0.138  location.timezone          String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.22
  5. 0.137  employment.jobLevel        String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.21
```

```
work_phone  (VARCHAR(20))

  1. 0.398  contact.phone              String   name 0.45  ref 0.00  type 1.00  desc 0.00  fuzzy 0.67
  2. 0.148  location.country           String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.35
  3. 0.147  location.timezone          String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.33
  4. 0.143  department.code            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.29
  5. 0.143  department.name            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.29
```

```
office_loc_id  (INT FK->locations.loc_id)

  1. 0.747  location.locationId        ObjectId name 0.67  ref 1.00  type 1.00  desc 0.33  fuzzy 0.76
  2. 0.305  employment.managerId       ObjectId name 0.23  ref 0.00  type 1.00  desc 0.33  fuzzy 0.43
  3. 0.303  _id                        ObjectId name 0.33  ref 0.00  type 1.00  desc 0.00  fuzzy 0.20
  4. 0.289  department.departmentId    ObjectId name 0.25  ref 0.00  type 1.00  desc 0.33  fuzzy 0.13
  5. 0.119  compensation.baseSalary    Number   name 0.00  ref 0.00  type 0.85  desc 0.00  fuzzy 0.21
```

```
is_remote  (TINYINT(1))  -- 0 or 1

  1. 0.625  employment.isRemote        Boolean  name 0.85  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.057  compensation.baseSalary    Number   name 0.00  ref 0.00  type 0.40  desc 0.00  fuzzy 0.12
  3. 0.053  meta.createdAt             ISODate  name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.67
  4. 0.034  location.timezone          String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.43
  5. 0.029  contact.email              String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.36
```

```
rec_stat  (CHAR(1))  -- A=Active, I=Inactive, T=Terminated

  1. 0.495  employment.status          String   name 0.45  ref 0.00  type 1.00  desc 1.00  fuzzy 0.63
  2. 0.148  department.code            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.35
  3. 0.148  location.code              String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.35
  4. 0.148  fullName.firstName         String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.35
  5. 0.147  employeeCode               String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.33
```

```
created_ts  (DATETIME)  -- record creation timestamp

  1. 0.422  meta.createdAt             ISODate  name 0.45  ref 0.00  type 1.00  desc 0.33  fuzzy 0.55
  2. 0.163  employment.startDate       ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.54
  3. 0.153  employment.endDate         ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.42
  4. 0.142  meta.updatedAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.27
  5. 0.032  fullName.lastName          String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.40
```

```
updated_ts  (DATETIME)  -- last update timestamp

  1. 0.422  meta.updatedAt             ISODate  name 0.45  ref 0.00  type 1.00  desc 0.33  fuzzy 0.55
  2. 0.149  meta.createdAt             ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.36
  3. 0.147  employment.endDate         ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.33
  4. 0.145  employment.startDate       ISODate  name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.31
  5. 0.052  fullName.lastName          String   name 0.00  ref 0.00  type 0.00  desc 0.33  fuzzy 0.24
```

## dept_info -> departments

7 source columns, 7 destination leaf paths.

```
dept_id  (INT PRIMARY KEY)

  1. 0.591  _id                        ObjectId name 0.50  ref 1.00  type 1.00  desc 0.00  fuzzy 0.27
  2. 0.516  parentDepartmentId         ObjectId name 0.67  ref 0.00  type 1.00  desc 0.00  fuzzy 0.79
  3. 0.302  headEmployeeId             ObjectId name 0.25  ref 0.00  type 1.00  desc 0.33  fuzzy 0.30
  4. 0.028  name                       String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.35
  5. 0.028  costCenterCode             String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.34
```

```
dept_cd  (VARCHAR(20) UNIQUE)

  1. 0.404  code                       String   name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.42
  2. 0.276  costCenterCode             String   name 0.25  ref 0.00  type 1.00  desc 0.00  fuzzy 0.39
  3. 0.213  parentDepartmentId         ObjectId name 0.25  ref 0.00  type 0.35  desc 0.00  fuzzy 0.57
  4. 0.145  name                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.32
  5. 0.057  isActive                   Boolean  name 0.00  ref 0.00  type 0.35  desc 0.00  fuzzy 0.19
```

```
dept_nm  (VARCHAR(100))

  1. 0.404  name                       String   name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.42
  2. 0.222  parentDepartmentId         ObjectId name 0.25  ref 0.00  type 0.35  desc 0.00  fuzzy 0.69
  3. 0.146  costCenterCode             String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.32
  4. 0.137  code                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.21
  5. 0.064  headEmployeeId             ObjectId name 0.00  ref 0.00  type 0.35  desc 0.00  fuzzy 0.28
```

```
parent_dept_id  (INT FK->dept_info.dept_id)  -- self-referencing

  1. 0.950  parentDepartmentId         ObjectId name 1.00  ref 1.00  type 1.00  desc 0.50  fuzzy 1.00
  2. 0.301  _id                        ObjectId name 0.33  ref 0.00  type 1.00  desc 0.00  fuzzy 0.18
  3. 0.291  headEmployeeId             ObjectId name 0.20  ref 0.00  type 1.00  desc 0.33  fuzzy 0.47
  4. 0.031  costCenterCode             String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.39
  5. 0.020  name                       String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.25
```

```
dept_head_id  (INT FK->emp_master.emp_id)

  1. 0.638  headEmployeeId             ObjectId name 0.50  ref 1.00  type 1.00  desc 0.33  fuzzy 0.44
  2. 0.425  parentDepartmentId         ObjectId name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.68
  3. 0.303  _id                        ObjectId name 0.33  ref 0.00  type 1.00  desc 0.00  fuzzy 0.20
  4. 0.028  costCenterCode             String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.35
  5. 0.022  name                       String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.27
```

```
cost_ctr_cd  (VARCHAR(20))  -- finance cost center code

  1. 0.775  costCenterCode             String   name 1.00  ref 0.00  type 1.00  desc 0.75  fuzzy 1.00
  2. 0.344  code                       String   name 0.33  ref 0.00  type 1.00  desc 0.25  fuzzy 0.40
  3. 0.128  name                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.10
  4. 0.064  parentDepartmentId         ObjectId name 0.00  ref 0.00  type 0.35  desc 0.00  fuzzy 0.28
  5. 0.063  headEmployeeId             ObjectId name 0.00  ref 0.00  type 0.35  desc 0.00  fuzzy 0.27
```

```
dept_stat  (CHAR(1))  -- A=Active, I=Inactive

  1. 0.476  isActive                   Boolean  name 0.50  ref 0.00  type 0.70  desc 1.00  fuzzy 0.52
  2. 0.219  parentDepartmentId         ObjectId name 0.25  ref 0.00  type 0.35  desc 0.00  fuzzy 0.65
  3. 0.149  costCenterCode             String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.36
  4. 0.143  name                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.29
  5. 0.135  code                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.19
```

## locations -> locations

8 source columns, 8 destination leaf paths.

```
loc_id  (INT PRIMARY KEY)

  1. 0.595  _id                        ObjectId name 0.50  ref 1.00  type 1.00  desc 0.00  fuzzy 0.31
  2. 0.034  timezone                   String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.42
  3. 0.026  stateOrProvince            String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.32
  4. 0.022  postalCode                 String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.27
  5. 0.021  city                       String   name 0.00  ref 0.00  type 0.00  desc 0.00  fuzzy 0.27
```

```
loc_cd  (VARCHAR(20) UNIQUE)

  1. 0.408  code                       String   name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.47
  2. 0.327  postalCode                 String   name 0.33  ref 0.00  type 1.00  desc 0.00  fuzzy 0.50
  3. 0.150  timezone                   String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.38
  4. 0.150  stateOrProvince            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.37
  5. 0.144  country                    String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.30
```

```
loc_nm  (VARCHAR(100))

  1. 0.408  name                       String   name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.47
  2. 0.158  timezone                   String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.48
  3. 0.150  stateOrProvince            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.37
  4. 0.139  city                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.24
  5. 0.139  code                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.24
```

```
city  (VARCHAR(80))

  1. 0.700  city                       String   name 1.00  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.164  country                    String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.55
  3. 0.141  postalCode                 String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.27
  4. 0.140  code                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.25
  5. 0.138  stateOrProvince            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.22
```

```
state_prov  (VARCHAR(80))

  1. 0.700  stateOrProvince            String   name 1.00  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.158  postalCode                 String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.48
  3. 0.142  timezone                   String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.27
  4. 0.138  city                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.22
  5. 0.138  code                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.22
```

```
country_cd  (CHAR(2))  -- ISO 3166-1 alpha-2

  1. 0.529  country                    String   name 0.50  ref 0.00  type 1.00  desc 1.00  fuzzy 0.74
  2. 0.410  code                       String   name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.50
  3. 0.335  postalCode                 String   name 0.33  ref 0.00  type 1.00  desc 0.00  fuzzy 0.61
  4. 0.150  city                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.38
  5. 0.145  stateOrProvince            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.31
```

```
postal_cd  (VARCHAR(20))

  1. 0.700  postalCode                 String   name 1.00  ref 0.00  type 1.00  desc 0.00  fuzzy 1.00
  2. 0.413  code                       String   name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.53
  3. 0.158  stateOrProvince            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.48
  4. 0.147  country                    String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.33
  5. 0.141  city                       String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.27
```

```
tz_cd  (VARCHAR(50))  -- IANA timezone

  1. 0.531  timezone                   String   name 0.50  ref 0.00  type 1.00  desc 1.00  fuzzy 0.76
  2. 0.408  code                       String   name 0.50  ref 0.00  type 1.00  desc 0.00  fuzzy 0.47
  3. 0.327  postalCode                 String   name 0.33  ref 0.00  type 1.00  desc 0.00  fuzzy 0.50
  4. 0.150  stateOrProvince            String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.37
  5. 0.144  country                    String   name 0.00  ref 0.00  type 1.00  desc 0.00  fuzzy 0.30
```

Total source fields covered: 34.
