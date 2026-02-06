CREATE TRIGGER item_audit
AFTER UPDATE ON ITEM
FOR EACH ROW
BEGIN
INSERT INTO ITEM_audit (column_name, old_value, new_value) VALUES ('ITEM_ID', :OLD.ITEM_ID, :NEW.ITEM_ID);
INSERT INTO ITEM_audit (column_name, old_value, new_value) VALUES ('ITEM_TYPE', :OLD.ITEM_TYPE, :NEW.ITEM_TYPE);
INSERT INTO ITEM_audit (column_name, old_value, new_value) VALUES ('ITEM_PRICE', :OLD.ITEM_PRICE, :NEW.ITEM_PRICE);
END;


CREATE TRIGGER empl_audit
AFTER INSERT ON EMPLOYEE
FOR EACH ROW
BEGIN
INSERT INTO EMPLOYEE_audit (column_name, old_value, new_value) VALUES ('EMPL_ID', :OLD.EMPL_ID, :NEW.EMPL_ID);
INSERT INTO EMPLOYEE_audit (column_name, old_value, new_value) VALUES ('EMPL_FNAME', :OLD.EMPL_FNAME, :NEW.EMPL_FNAME);
INSERT INTO EMPLOYEE_audit (column_name, old_value, new_value) VALUES ('EMPL_LNAME', :OLD.EMPL_LNAME, :NEW.EMPL_LNAME);
INSERT INTO EMPLOYEE_audit (column_name, old_value, new_value) VALUES ('SALARY', :OLD.SALARY, :NEW.SALARY);
END;


CREATE TRIGGER item_insert_audit
AFTER INSERT ON ITEM
FOR EACH ROW
BEGIN
INSERT INTO ITEM_audit (column_name, old_value, new_value) VALUES ('ITEM_ID', :OLD.ITEM_ID, :NEW.ITEM_ID);
INSERT INTO ITEM_audit (column_name, old_value, new_value) VALUES ('ITEM_TYPE', :OLD.ITEM_TYPE, :NEW.ITEM_TYPE);
INSERT INTO ITEM_audit (column_name, old_value, new_value) VALUES ('ITEM_PRICE', :OLD.ITEM_PRICE, :NEW.ITEM_PRICE);
END;


